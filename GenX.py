import google.generativeai as gemini 
import streamlit as st

gemini.configure(api_key=st.secrets["GOOGLE_API_KEY"])

st.title("GenX")

@st.cache_resource
def load_model():
    model = gemini.GenerativeModel('gemini-2.0-flash')
    print("model loaded...")
    return model

model = load_model()

if "chat_session" not in st.session_state:    
    st.session_state["chat_session"] = model.start_chat(history=[]) 

for content in st.session_state.chat_session.history:
    with st.chat_message("ai" if content.role == "model" else "user"):
        st.markdown(content.parts[0].text)

if prompt := st.chat_input("메시지를 입력하세요."):    
    with st.chat_message("user"):
        st.markdown(prompt)    
    with st.chat_message("ai"):        
        message_placeholder = st.empty()
        full_response = ""
        with st.spinner("메시지 처리 중입니다."):
            response = st.session_state.chat_session.send_message(prompt, stream=True)
            for chunk in response:            
                full_response += chunk.text
                message_placeholder.markdown(full_response)    