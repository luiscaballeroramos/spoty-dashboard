import json

import pandas as pd
import streamlit as st


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


# =============================================================================
# Header
# =============================================================================

st.title("🎵 SPOTY")


# =============================================================================
# Database query
# =============================================================================

query = """
SELECT
    le.played_at,
    le.track_id,
    le.context_source,
    le.context_type,

    t.name AS track_name,
    t.duration_ms,
    t.popularity AS track_popularity,
    t.artists_ids,

    a.name AS album_name,
    a.images AS album_images,
    a.release_year

FROM listening_events AS le

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


summary_query = """
SELECT
    (SELECT COUNT(*) FROM tracks) AS total_tracks,
    (SELECT COUNT(*) FROM artists) AS total_artists,
    (SELECT COUNT(*) FROM albums) AS total_albums
"""

summary_df = conn.query(
    summary_query,
    ttl=0,
)

summary = summary_df.iloc[0]


# =============================================================================
# Empty database
# =============================================================================

if df.empty:
    st.info("No hay listening events registrados todavía.")
    st.stop()


# =============================================================================
# Get artist names
# =============================================================================

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
        f"'{artist_id.replace(chr(39), chr(39) * 2)}'"
        for artist_id in artist_ids
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

        names = [
            artist_names.get(artist_id, artist_id)
            for artist_id in ids
        ]

        return ", ".join(names)

    except (json.JSONDecodeError, TypeError):
        return "-"


df["artist"] = df["artists_ids"].apply(get_artists)


# =============================================================================
# Format data
# =============================================================================

df["played_at"] = pd.to_datetime(
    df["played_at"],
    unit="s",
    utc=True,
).dt.tz_convert("Europe/Rome")

df["played_at"] = df["played_at"].dt.strftime(
    "%d/%m/%Y %H:%M"
)

df["duration"] = df["duration_ms"].apply(
    format_duration
)

df["album_image"] = df["album_images"].apply(
    get_image
)


# =============================================================================
# Last played
# =============================================================================

last = df.iloc[0]

st.divider()

col1, col2 = st.columns([1, 4])

with col1:
    if last["album_image"]:
        st.image(
            last["album_image"],
            width=100,
        )

with col2:
    st.markdown(
        f"### {last['track_name']}"
    )

    st.write(
        f"**{last['artist']}** · {last['album_name']}"
    )

    st.caption(
        f"🕐 {last['played_at']}"
    )


st.divider()


# =============================================================================
# Statistics
# =============================================================================

col1, col2, col3 = st.columns(3)

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


st.divider()


# =============================================================================
# Listening events table
# =============================================================================

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
