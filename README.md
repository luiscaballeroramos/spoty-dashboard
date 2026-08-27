# spoty
<!-- create env -->
python -m venv venv

<!-- activate env -->
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
venv\Scripts\activate

<!-- deactivate env -->
deactivate

<!-- install requirements -->
pip install -r requirements.txt

<!-- documentation Streamlit linked to Neon -->
https://docs.streamlit.io/develop/tutorials/databases/neon?utm_source=chatgpt.com

<!-- run streamlit locally -->
streamlit run streamlit_app.py
