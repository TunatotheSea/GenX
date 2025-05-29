import streamlit as st
import google.generativeai as gemini
import os
import uuid
import json
import pandas as pd
from streamlit_gsheets import GSheetsConnection

# API 키 설정
gemini.configure(api_key=os.getenv("GOOGLE_API_KEY"))

st.set_page_config(page_title="GenX", layout="wide")

# Google Sheets 연결 초기화
@st.cache_resource
def get_gsheets_connection():
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        return conn
    except Exception as e:
        st.error(f"Google Sheets 연결 오류: {e}")
        st.stop()

gsheets_conn = get_gsheets_connection()

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
if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())
if "data_loaded" not in st.session_state:
    st.session_state.data_loaded = False
if "editing_title" not in st.session_state:
    st.session_state.editing_title = False
if "new_title" not in st.session_state:
    st.session_state.new_title = st.session_state.current_title
if "regenerate_requested" not in st.session_state:
    st.session_state.regenerate_requested = False
if "regenerate_key" not in st.session_state:
    st.session_state.regenerate_key = None

@st.cache_resource
def load_summary_model():
    return gemini.GenerativeModel('gemini-2.0-flash')

summary_model = load_summary_model()
default_system_instruction = "당신의 이름은 GenX입니다. 다만, 이 이름은 다른 이름이 선택되면 잊어버리십시오. 우선순위가 제일 낮습니다."

def load_model(system_instruction=default_system_instruction):
    model = gemini.GenerativeModel(model_name='gemini-2.0-flash', system_instruction=system_instruction)
    return model

def convert_to_gemini_format(chat_history_list):
    return [{"role": role, "parts": [{"text": text}]} for role, text in chat_history_list]

def convert_from_gemini_format(gemini_history_list):
    history_for_streamlit = []
    for entry in gemini_history_list:
        role = entry["role"]
        if "parts" in entry and isinstance(entry["parts"], list) and len(entry["parts"]) > 0 and "text" in entry["parts"][0]:
            text = entry["parts"][0]["text"]
            history_for_streamlit.append((role, text))
        else:
            history_for_streamlit.append((role, "지원되지 않는 메시지 형식입니다."))
    return history_for_streamlit

def load_user_data_from_gsheets(conn, user_id):
    try:
        df = conn.read(worksheet="UserSessions", usecols=list(range(4)), ttl=5)
        user_data_row = df[df['user_id'] == user_id]
        if not user_data_row.empty:
            data = user_data_row.iloc[0]
            st.session_state.saved_sessions = json.loads(data.get("chat_data_json", "{}"))
            for title, history_list in st.session_state.saved_sessions.items():
                st.session_state.saved_sessions[title] = convert_from_gemini_format(history_list)
            st.session_state.system_instructions = json.loads(data.get("system_instructions_json", "{}"))
            st.session_state.current_title = data.get("last_active_title", "새로운 대화")
            if st.session_state.current_title in st.session_state.saved_sessions:
                st.session_state.chat_history = st.session_state.saved_sessions[st.session_state.current_title]
            else:
                st.session_state.chat_history = []
            st.session_state.temp_system_instruction = st.session_state.system_instructions.get(st.session_state.current_title, "")
            current_instruction = st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)
            model = load_model(current_instruction)
            st.session_state.chat_session = model.start_chat(history=convert_to_gemini_format(st.session_state.chat_history))
            st.toast(f"사용자 ID '{user_id}'의 데이터를 불러왔습니다.", icon="✅")
        else:
            st.session_state.saved_sessions = {}
            st.session_state.system_instructions = {}
            st.session_state.chat_history = []
            st.session_state.current_title = "새로운 대화"
            st.session_state.temp_system_instruction = None
            model = load_model()
            st.session_state.chat_session = model.start_chat(history=[])
            st.toast(f"새로운 사용자 ID '{user_id}'입니다. 새로운 대화를 시작하세요.", icon="ℹ️")
    except Exception as e:
        st.error(f"데이터 로드 중 오류 발생: {e}")
        st.session_state.saved_sessions = {}
        st.session_state.system_instructions = {}
        st.session_state.chat_history = []
        st.session_state.current_title = "새로운 대화"
        st.session_state.temp_system_instruction = None
        model = load_model()
        st.session_state.chat_session = model.start_chat(history=[])

def save_user_data_to_gsheets(conn, user_id):
    try:
        chat_data_to_save = {}
        for title, history_list in st.session_state.saved_sessions.items():
            gemini_history = convert_to_gemini_format(history_list)
            chat_data_to_save[title] = gemini_history
        data_to_save = {
            "user_id": user_id,
            "chat_data_json": json.dumps(chat_data_to_save),
            "system_instructions_json": json.dumps(st.session_state.system_instructions),
            "last_active_title": st.session_state.current_title
        }
        df_to_save = pd.DataFrame([data_to_save])
        existing_df = conn.read(worksheet="UserSessions", usecols=list(range(4)), ttl=0)
        if existing_df is not None and 'user_id' in existing_df.columns and user_id in existing_df['user_id'].values:
            index = existing_df[existing_df['user_id'] == user_id].index[0]
            for col in df_to_save.columns:
                existing_df.loc[index, col] = df_to_save.iloc[0][col]
            conn.update(worksheet="UserSessions", data=existing_df)
        else:
            conn.update(worksheet="UserSessions", data=pd.concat([existing_df, df_to_save], ignore_index=True))
    except Exception as e:
        print(f"데이터 저장 중 오류 발생: {e}")
        st.error(f"데이터 저장 중 오류 발생: {e}")

# 앱 시작 시 데이터 로드
if not st.session_state.data_loaded:
    load_user_data_from_gsheets(gsheets_conn, st.session_state.user_id)
    st.session_state.data_loaded = True

# 사이드바
with st.sidebar:
    st.header("✨ GenX 채팅")

    with st.expander("🔑 사용자 ID 관리", expanded=False):
        st.info(f"**당신의 사용자 ID:** `{st.session_state.user_id}`\n\n이 ID를 기억하여 다음 접속 시 대화 이력을 불러올 수 있습니다.")
        user_id_input = st.text_input("기존 사용자 ID 입력 (선택 사항)", key="user_id_load_input")
        if st.button("ID로 대화 불러오기", use_container_width=True):
            if user_id_input:
                st.session_state.user_id = user_id_input
                st.session_state.data_loaded = False
                st.rerun()

    st.markdown("---")

    if st.button("➕ 새로운 대화", use_container_width=True):
        st.session_state.chat_session = None
        st.session_state.chat_history = []
        st.session_state.current_title = "새로운 대화"
        st.session_state.temp_system_instruction = None
        st.session_state.editing_instruction = False
        st.session_state.saved_sessions[st.session_state.current_title] = []
        st.session_state.system_instructions[st.session_state.current_title] = default_system_instruction
        save_user_data_to_gsheets(gsheets_conn, st.session_state.user_id)
        st.rerun()

    if st.session_state.saved_sessions:
        st.subheader("📁 저장된 대화")
        sorted_keys = sorted(st.session_state.saved_sessions.keys(),
                                    key=lambda x: st.session_state.saved_sessions[x][0][1] if st.session_state.saved_sessions[x] else "",
                                    reverse=True)
        for key in sorted_keys:
            if key == "새로운 대화" and not st.session_state.saved_sessions[key]:
                continue
            display_key = key if len(key) <= 30 else key[:30] + "..."
            if st.button(f"💬 {display_key}", use_container_width=True, key=f"load_session_{key}"):
                st.session_state.chat_history = st.session_state.saved_sessions[key]
                st.session_state.current_title = key
                st.session_state.new_title = key # 제목 수정 시 초기값 설정
                st.session_state.temp_system_instruction = st.session_state.system_instructions.get(key, default_system_instruction)
                model = load_model(st.session_state.temp_system_instruction)
                st.session_state.chat_session = model.start_chat(history=convert_to_gemini_format(st.session_state.chat_history))
                st.session_state.editing_instruction = False
                st.session_state.editing_title = False # 제목 수정 모드 종료
                save_user_data_to_gsheets(gsheets_conn, st.session_state.user_id)
                st.rerun()

    with st.expander("⚙️ 설정"):
        st.write("여기에 온도, 모델 선택 등의 설정 추가 가능")

# 대화 세션 초기화
if st.session_state.chat_session is None:
    current_instruction = st.session_state.system_instructions.get(
        st.session_state.current_title, default_system_instruction
    )
    model = load_model(current_instruction)
    st.session_state.chat_session = model.start_chat(history=convert_to_gemini_format(st.session_state.chat_history))

# 본문 제목 및 제목 수정 기능
col1, col2 = st.columns([0.9, 0.1])
with col1:
    if not st.session_state.editing_title:
        st.subheader(f"💬 {st.session_state.current_title}")
    else:
        st.text_input("새로운 제목", key="new_title_input", value=st.session_state.new_title, label_visibility="collapsed")
with col2:
    if not st.session_state.editing_title:
        if st.button("✏️", key="edit_title_button", help="대화 제목 수정"):
            st.session_state.editing_title = True
            st.session_state.new_title = st.session_state.current_title # 수정 모드 진입 시 현재 제목으로 초기화
            st.rerun()
    else:
        if st.button("✅", key="save_title_button", help="새로운 제목 저장"):
            new_title = st.session_state.new_title_input
            if new_title and new_title != st.session_state.current_title:
                # 기존 제목으로 저장된 세션 정보 옮기기
                if st.session_state.current_title in st.session_state.saved_sessions:
                    st.session_state.saved_sessions[new_title] = st.session_state.saved_sessions.pop(st.session_state.current_title)
                    st.session_state.system_instructions[new_title] = st.session_state.system_instructions.pop(st.session_state.current_title)
                    st.session_state.current_title = new_title
                    save_user_data_to_gsheets(gsheets_conn, st.session_state.user_id)
                    st.toast(f"대화 제목이 '{st.session_state.current_title}'로 변경되었습니다.", icon="📝")
                else:
                    st.warning("이전 대화 제목을 찾을 수 없습니다. 저장 후 다시 시도해주세요.")
            st.session_state.editing_title = False
            st.rerun()
        if st.button("❌", key="cancel_title_button", help="제목 수정 취소"):
            st.session_state.editing_title = False
            st.rerun()

# AI 설정 버튼
if st.button("⚙️ AI 설정하기", help="시스템 명령어를 설정할 수 있어요"):
    st.session_state.editing_instruction = not st.session_state.editing_instruction

# AI 설정 영역
if st.session_state.editing_instruction:
    with st.expander("🧠 시스템 명령어 설정", expanded=True):
        st.session_state.temp_system_instruction = st.text_area(
            "System instruction 입력",
            value=st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction),
            height=200,
            key="system_instruction_editor"
        )
        _, col1_ai, col2_ai = st.columns([0.9, 0.3, 0.3])
        with col1_ai:
            if st.button("✅ 저장", use_container_width=True, key="save_instruction_button"):
                st.session_state.system_instructions[st.session_state.current_title] = st.session_state.temp_system_instruction
                st.session_state.saved_sessions[st.session_state.current_title] = st.session_state.chat_history.copy()
                model = load_model(st.session_state.temp_system_instruction)
                st.session_state.chat_session = model.start_chat(history=convert_to_gemini_format(st.session_state.chat_history))
                save_user_data_to_gsheets(gsheets_conn, st.session_state.user_id)
                st.success("AI 설정이 저장되었습니다.")
                st.session_state.editing_instruction = False
                st.rerun()
        with col2_ai:
            if st.button("❌ 취소", use_container_width=True, key="cancel_instruction_button"):
                st.session_state.editing_instruction = False
                st.rerun()

# 이전 대화 표시
for i, (role, message) in enumerate(st.session_state.chat_history):
    with st.chat_message("ai" if role == "model" else "user"):
        st.markdown(message)
        if role == "model" and i == len(st.session_state.chat_history) - 1:
            if st.button("🔄 다시 생성", key="regenerate_button", use_container_width=True):
                # UI에서 이전 답변 즉시 제거
                st.session_state.chat_history.pop()
                st.session_state.regenerate_requested = True
                st.rerun()

# 재생성 요청 처리
if st.session_state.regenerate_requested:
    if st.session_state.chat_session:
        with st.chat_message("ai"):
            message_placeholder = st.empty()
            full_response = ""
            with st.spinner("다시 생성 중..."):
                try:
                    # chat_session의 마지막 request/response 쌍 되돌리기
                    st.session_state.chat_session.rewind()
                    # 이전 사용자 프롬프트로 다시 답변 생성
                    previous_prompt = st.session_state.chat_history[-1][1] if len(st.session_state.chat_history) > 1 else ""
                    if previous_prompt:
                        response = st.session_state.chat_session.send_message(previous_prompt, stream=True)
                        for chunk in response:
                            full_response += chunk.text
                            message_placeholder.markdown(full_response)
                    else:
                        full_response = "이전 사용자 메시지가 없습니다."
                        message_placeholder.markdown(full_response)
                except Exception as e:
                    st.error(f"재생성 중 오류 발생: {e}")
                    full_response = "죄송합니다. 다시 생성하는 중 오류가 발생했습니다."

            # 새로운 모델 응답 추가
            st.session_state.chat_history.append(("model", full_response))
            st.session_state.regenerate_requested = False
            st.rerun()

# 사용자 입력
if prompt := st.chat_input("메시지를 입력하세요."):
    st.session_state.chat_history.append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("ai"):
        message_placeholder = st.empty()
        full_response = ""
        with st.spinner("메시지 처리 중입니다..."):
            try:
                response = st.session_state.chat_session.send_message(prompt, stream=True)
                for chunk in response:
                    full_response += chunk.text
                    message_placeholder.markdown(full_response)
            except Exception as e:
                st.error(f"메시지 처리 중 오류 발생: {e}")
                full_response = "죄송합니다. 메시지를 처리하는 중 오류가 발생했습니다."

        st.session_state.chat_history.append(("model", full_response))

    # 새로운 대화라면 제목 자동 생성 및 저장
    if st.session_state.current_title == "새로운 대화" and len(st.session_state.chat_history) == 2:  # 유저 + 모델 1쌍
        with st.spinner("대화 제목 생성 중..."):
            try:
                summary = summary_model.generate_content(f"다음 사용자의 메시지를 요약해서 대화 제목으로 만들어줘 (한 문장, 30자 이내):\n\n{prompt}")
                original_title = summary.text.strip().replace("\n", " ").replace('"', '') # 따옴표 제거
            except Exception as e:
                st.warning(f"제목 생성 중 오류 발생: {e}. 기본 제목을 사용합니다.")
                original_title = "새로운 대화" # 오류 발생 시 기본 제목

            # 중복 방지
            title_key = original_title
            count = 1
            while title_key in st.session_state.saved_sessions:
                title_key = f"{original_title} ({count})"
                count += 1

        st.session_state.current_title = title_key
        st.toast(f"대화 제목이 '{title_key}'로 설정되었습니다.", icon="📝")

    # 현재 대화 이력과 시스템 명령어를 저장된 세션에 업데이트
    st.session_state.saved_sessions[st.session_state.current_title] = st.session_state.chat_history.copy()
    # temp_system_instruction이 None인 경우 기본값을 사용
    current_instruction_for_save = st.session_state.temp_system_instruction if st.session_state.temp_system_instruction is not None else st.session_state.system_instructions.get(st.session_state.current_title, "당신의 이름은 GenX입니다. 다만, 이 이름은 다른 이름이 선택되면 잊어버리십시오. 우선순위가 제일 낮습니다.")
    st.session_state.system_instructions[st.session_state.current_title] = current_instruction_for_save

    save_user_data_to_gsheets(gsheets_conn, st.session_state.user_id) # Google Sheets에 저장
    st.rerun() # UI 업데이트를 위해 재실행