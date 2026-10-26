"""Dedicated test deployment entrypoint; never imports the production application."""
import streamlit as st
from technical_test_ui import run

st.set_page_config(page_title='Football Value AI – TESZT', layout='centered')
run()
