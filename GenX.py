import streamlit as st
import google.generativeai as gemini

# API 키 설정
gemini.configure(api_key=st.secrets["GOOGLE_API_KEY"])

st.set_page_config(page_title="GenX", layout="wide")

# 세션 상태 초기화
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "chat_session" not in st.session_state:
    st.session_state.chat_session = None

if "saved_sessions" not in st.session_state:
    st.session_state.saved_sessions = {}

if "current_title" not in st.session_state:
    st.session_state.current_title = "새로운 대화"

if "system_instructions" not in st.session_state:
    st.session_state.system_instructions = {}

if "temp_system_instruction" not in st.session_state:
    st.session_state.temp_system_instruction = None

if "editing_instruction" not in st.session_state:
    st.session_state.editing_instruction = False

@st.cache_resource
def load_summary_model():
    return gemini.GenerativeModel(
        'gemini-2.0-flash'
    )

summary_model = load_summary_model()

# 모델 로딩 함수
def load_model(system_instruction=None):
    model = gemini.GenerativeModel(
        model_name='gemini-2.0-flash',
        system_instruction=system_instruction
    )
    return model

def convert_to_gemini_format(chat_history):
    return [{"role": role, "parts": [text]} for role, text in chat_history]

# 사이드바
with st.sidebar:
    st.header("✨ GenX 채팅")

    if st.button("➕ 새로운 대화", use_container_width=True):
        st.session_state.chat_session = None
        st.session_state.chat_history = []
        st.session_state.current_title = "새로운 대화"
        st.session_state.editing_instruction = False

    if st.session_state.saved_sessions:
        st.subheader("📁 저장된 대화")
        for key in st.session_state.saved_sessions.keys():
            display_key = key if len(key) <= 30 else key[:30] + "..."
            if st.button(f"💬 {display_key}", use_container_width=True, key=key):
                st.session_state.chat_history = st.session_state.saved_sessions[key]
                st.session_state.current_title = key
                st.session_state.temp_system_instruction = st.session_state.system_instructions.get(key, "")
                model = load_model(st.session_state.temp_system_instruction)
                st.session_state.chat_session = model.start_chat(history=convert_to_gemini_format(st.session_state.chat_history))
                st.session_state.editing_instruction = False

    with st.expander("⚙️ 설정"):
        st.write("여기에 온도, 모델 선택 등의 설정 추가 가능")

# 대화 세션 초기화
if st.session_state.chat_session is None:
    current_instruction = st.session_state.system_instructions.get(
        st.session_state.current_title, "당신의 이름은 GenX입니다. 다만, 이 이름은 다른 이름이 선택되면 잊어버리십시오. 우선순위가 제일 낮습니다."
    )
    model = load_model(current_instruction)
    st.session_state.chat_session = model.start_chat(history=[])
    st.session_state.chat_history = []

# 본문 제목
st.subheader(f"💬 {st.session_state.current_title}")

# AI 설정 버튼
if st.button("⚙️ AI 설정하기", help="시스템 명령어를 설정할 수 있어요"):
    st.session_state.editing_instruction = not st.session_state.editing_instruction

# AI 설정 영역
if st.session_state.editing_instruction:
    with st.expander("🧠 시스템 명령어 설정", expanded=True):
        st.session_state.temp_system_instruction = st.text_area(
            "System instruction 입력",
            value=st.session_state.system_instructions.get(st.session_state.current_title, ""),
            height=200,
            key="system_instruction_editor"
        )

        _, col1, col2 = st.columns([0.9, 0.3, 0.3])
        with col1:
            if st.button("✅ 저장", use_container_width=True):
                # 설정 저장 및 모델 재로드
                st.session_state.system_instructions[st.session_state.current_title] = st.session_state.temp_system_instruction
                model = load_model(st.session_state.temp_system_instruction)
                st.session_state.chat_session = model.start_chat(history=convert_to_gemini_format(st.session_state.chat_history))
                st.success("AI 설정이 저장되었습니다.")
                st.session_state.editing_instruction = False

        with col2:
            if st.button("❌ 취소", use_container_width=True):
                st.session_state.editing_instruction = False

# 이전 대화 표시
for role, message in st.session_state.chat_history:
    with st.chat_message("ai" if role == "model" else "user"):
        st.markdown(message)

# 사용자 입력
if prompt := st.chat_input("메시지를 입력하세요."):
    st.session_state.chat_history.append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("ai"):
        message_placeholder = st.empty()
        full_response = ""
        with st.spinner("메시지 처리 중입니다..."):
            response = st.session_state.chat_session.send_message(prompt, stream=True)
            for chunk in response:
                full_response += chunk.text
                message_placeholder.markdown(full_response)

        st.session_state.chat_history.append(("model", full_response))

    # 새로운 대화라면 제목 자동 생성 및 저장
    if len(st.session_state.chat_history) == 2:  # 유저 + 모델 1쌍
        with st.spinner("대화 제목 생성 중..."):
            summary = summary_model.generate_content(f"다음 사용자의 메시지를 요약해서 대화 제목으로 만들어줘 (한 문장):\n\n{prompt}")
            original_title = summary.text.strip().replace("\n", " ")

            # 중복 방지
            title_key = original_title
            count = 1
            while title_key in st.session_state.saved_sessions:
                title_key = f"{original_title} ({count})"
                count += 1

        st.session_state.current_title = title_key
    st.session_state.saved_sessions[st.session_state.current_title] = st.session_state.chat_history.copy()
    st.session_state.system_instructions[st.session_state.current_title] = st.session_state.temp_system_instruction
