import json
import os
from datetime import timedelta, timezone

import pandas as pd
import streamlit as st


def load_streamlit_secrets_to_env() -> None:
    """Expose local Streamlit secrets as environment variables for the installed Spoty package."""
    try:
        secrets = st.secrets
    except Exception:
        return

    spotify_keys = {
        "SPOTIFY_CLIENT_ID": "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET": "SPOTIFY_CLIENT_SECRET",
        "SPOTIFY_REDIRECT_URI": "SPOTIFY_REDIRECT_URI",
    }

    for env_key, secret_key in spotify_keys.items():
        value = secrets.get(secret_key)
        if value is not None:
            os.environ.setdefault(env_key, str(value))

    neon_url = None
    try:
        neon_url = secrets["connections"]["neon"]["url"]
    except Exception:
        neon_url = None

    if neon_url:
        os.environ.setdefault("DATABASE_URL", str(neon_url))


register_listeningevents = None


def get_register_listeningevents():
    global register_listeningevents

    if register_listeningevents is not None:
        return register_listeningevents

    load_streamlit_secrets_to_env()

    try:
        from _registration import register_listeningevents as imported_function
    except Exception:
        return None

    register_listeningevents = imported_function
    return register_listeningevents


# =============================================================================
# Page configuration
# =============================================================================

st.set_page_config(
    page_title="SPOTY",
    page_icon="🎵",
    layout="wide",
)


# =============================================================================
# Database connection
# =============================================================================

conn = st.connection("neon", type="sql")


# =============================================================================
# Timezone
# =============================================================================

TIMEZONE_OFFSET_HOURS = +4
LOCAL_TIMEZONE = timezone(timedelta(hours=TIMEZONE_OFFSET_HOURS))


# =============================================================================
# Helpers
# =============================================================================


def format_duration(duration_ms: int | float | None) -> str:
    """Convert milliseconds to M:SS format."""
    if pd.isna(duration_ms):
        return "-"

    total_seconds = int(duration_ms / 1000)
    minutes, seconds = divmod(total_seconds, 60)

    return f"{minutes}:{seconds:02d}"


def get_image(images: str | None) -> str | None:
    """Get the first image URL from a JSON serialized image list."""
    if not images:
        return None

    try:
        parsed = json.loads(images)

        if isinstance(parsed, list) and parsed:
            return parsed[0]

    except (json.JSONDecodeError, TypeError):
        pass

    return None


# # =============================================================================
# # Header
# # =============================================================================

# st.title("🎵 SPOTY")


# =============================================================================
# Dashboard actions
# =============================================================================

register_function = get_register_listeningevents()

left_col, right_col = st.columns([1, 6])

with left_col:
    if register_function is None:
        st.warning(
            "No se pudo importar la función de registro de Spoty. "
            "Asegúrate de tener instaladas las dependencias del repositorio y configuradas las variables de entorno de Spotify."
        )
    else:
        if st.button(
            "↻", key="register_listeningevents", help="Registrar escuchas recientes"
        ):
            try:
                with st.spinner("Ejecutando registro de escuchas recientes..."):
                    register_function()
                st.toast("Registro completado.", icon="✅")
            except Exception as exc:
                st.error(f"Error al ejecutar el registro: {exc}")


# =============================================================================
# Auto-refreshing content
# =============================================================================


@st.fragment(run_every="10s")
def spotify_dashboard():

    # =========================================================================
    # Database query
    # =========================================================================

    query = """
    WITH track_stats AS (
        SELECT
            track_id,
            COUNT(*) AS track_play_count,
            CEIL(
                100.0
                * ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC, track_id)
                / NULLIF(COUNT(*) OVER (), 0)
            )::int AS track_top_percent
        FROM listening_events
        GROUP BY track_id
    )
    SELECT
        le.played_at,
        le.track_id,
        le.context_source,
        le.context_type,
        ts.track_play_count,
        ts.track_top_percent,

        t.name AS track_name,
        t.duration_ms,
        t.popularity AS track_popularity,
        t.artists_ids,

        a.name AS album_name,
        a.images AS album_images,
        a.release_year

    FROM listening_events AS le

    LEFT JOIN track_stats AS ts
        ON le.track_id = ts.track_id

    LEFT JOIN tracks AS t
        ON le.track_id = t.id

    LEFT JOIN albums AS a
        ON t.album_id = a.id

    ORDER BY le.played_at DESC

    LIMIT 100
    """

    df = conn.query(
        query,
        ttl=0,
    )

    # =========================================================================
    # Summary query
    # =========================================================================

    summary_query = """
    SELECT
        (SELECT COUNT(*) FROM tracks) AS total_tracks,
        (SELECT COUNT(*) FROM artists) AS total_artists,
        (SELECT COUNT(*) FROM albums) AS total_albums,
        (SELECT COUNT(*) FROM liked_tracks) AS total_liked_tracks,
        (SELECT COUNT(*) FROM listening_events) AS total_listening_events
    """

    summary_df = conn.query(
        summary_query,
        ttl=0,
    )

    summary = summary_df.iloc[0]

    # =========================================================================
    # Empty database
    # =========================================================================

    if df.empty:
        st.info("No hay listening events registrados todavía.")
        return

    # =========================================================================
    # Get artist names
    # =========================================================================

    artist_ids = set()

    for value in df["artists_ids"].dropna():
        try:
            ids = json.loads(value)

            if isinstance(ids, list):
                artist_ids.update(ids)

        except (json.JSONDecodeError, TypeError):
            continue

    artist_names = {}

    if artist_ids:

        # Build a PostgreSQL array literal safely.
        artist_array = ",".join(
            f"'{artist_id.replace(chr(39), chr(39) * 2)}'" for artist_id in artist_ids
        )

        artists_query = f"""
        SELECT
            id,
            name
        FROM artists
        WHERE id = ANY(ARRAY[{artist_array}]::text[])
        """

        artists_df = conn.query(
            artists_query,
            ttl=0,
        )

        artist_names = dict(
            zip(
                artists_df["id"],
                artists_df["name"],
            )
        )

    def get_artists(value: str | None) -> str:
        """Convert artist IDs stored as JSON into artist names."""
        if not value:
            return "-"

        try:
            ids = json.loads(value)

            if not isinstance(ids, list):
                return "-"

            names = [artist_names.get(artist_id, artist_id) for artist_id in ids]

            return ", ".join(names)

        except (json.JSONDecodeError, TypeError):
            return "-"

    df["artist"] = df["artists_ids"].apply(get_artists)

    # =========================================================================
    # Format data
    # =========================================================================

    df["played_at"] = pd.to_datetime(
        df["played_at"],
        unit="s",
        utc=True,
    ).dt.tz_convert(LOCAL_TIMEZONE)

    df["played_at"] = df["played_at"].dt.strftime("%d/%m/%Y %H:%M")

    df["duration"] = df["duration_ms"].apply(format_duration)

    df["album_image"] = df["album_images"].apply(get_image)

    # =========================================================================
    # Last played
    # =========================================================================

    last = df.iloc[0]

    current_track_play_count = (
        int(last["track_play_count"]) if pd.notna(last["track_play_count"]) else 0
    )
    current_track_top_percent = (
        int(last["track_top_percent"]) if pd.notna(last["track_top_percent"]) else None
    )

    col1, col2 = st.columns([1, 4])

    with col1:
        if last["album_image"]:
            st.image(
                last["album_image"],
                use_container_width=True,
            )

    with col2:
        st.markdown(f"### {last['track_name']}")
        st.write(f"👤 **{last['artist']}**")
        st.write(f"💿 **{last['album_name']}**")
        st.write(
            f"🎧 **x{current_track_play_count} ({current_track_top_percent if current_track_top_percent is not None else '-'}%)**"
        )
        st.write(f"🕐 **{last['played_at']}**")

    st.divider()

    # =========================================================================
    # Statistics
    # =========================================================================

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric(
            "🎵 Tracks",
            int(summary["total_tracks"]),
        )

    with col2:
        st.metric(
            "👤 Artistas",
            int(summary["total_artists"]),
        )

    with col3:
        st.metric(
            "💿 Álbumes",
            int(summary["total_albums"]),
        )

    with col4:
        st.metric(
            "💜 Liked Songs",
            int(summary["total_liked_tracks"]),
        )

    with col5:
        st.metric(
            "🎧 Listening Events",
            int(summary["total_listening_events"]),
        )

    row2_col1, row2_col2, row2_col3, row2_col4, row2_col5 = st.columns(5)

    st.divider()

    # =========================================================================
    # Listening events table
    # =========================================================================

    st.subheader("🎧 Historial")

    display_df = df[
        [
            "played_at",
            "track_name",
            "artist",
            "album_name",
            # "duration",
            # "track_popularity",
            # "context_source",
        ]
    ].rename(
        columns={
            "played_at": "🕐 Reproducido",
            "track_name": "🎵 Canción",
            "artist": "👤 Artista",
            "album_name": "💿 Álbum",
            # "duration": "⏱️ Duración",
            # "track_popularity": "🔥 Popularidad",
            # "context_source": "📍 Fuente",
        }
    )

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
    )


# =============================================================================
# Run dashboard
# =============================================================================

spotify_dashboard()
