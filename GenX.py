import streamlit as st
import google.generativeai as gemini
import os
import uuid
import json
import pandas as pd
from streamlit_gsheets import GSheetsConnection

# API 키 설정
# GOOGLE_API_KEY 환경 변수가 설정되어 있어야 합니다.
gemini.configure(api_key=os.getenv("GOOGLE_API_KEY"))

st.set_page_config(page_title="GenX", layout="wide")

# Google Sheets 연결 초기화
# Streamlit Cloud에 배포하는 경우, secrets.toml에서 connections.gsheets를 로드합니다.
# 로컬에서 실행하는 경우, GOOGLE_APPLICATION_CREDENTIALS 환경 변수가 설정되어 있어야 합니다.
@st.cache_resource
def get_gsheets_connection():
    """Google Sheets 연결을 캐시하여 여러 번 초기화되지 않도록 합니다."""
    try:
        # st.connection을 사용하여 Google Sheets 연결
        conn = st.connection("gsheets", type=GSheetsConnection)
        return conn
    except Exception as e:
        st.error(f"Google Sheets 연결 오류: {e}")
        st.stop() # 연결 실패 시 앱 중지

gsheets_conn = get_gsheets_connection()

# 세션 상태 초기화
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "chat_session" not in st.session_state:
    st.session_state.chat_session = None

if "saved_sessions" not in st.session_state:
    st.session_state.saved_sessions = {} # {title: chat_history_list}

if "current_title" not in st.session_state:
    st.session_state.current_title = "새로운 대화"

if "system_instructions" not in st.session_state:
    st.session_state.system_instructions = {} # {title: instruction_string}

if "temp_system_instruction" not in st.session_state:
    st.session_state.temp_system_instruction = None

if "editing_instruction" not in st.session_state:
    st.session_state.editing_instruction = False

if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4()) # 고유한 사용자 ID 생성

if "data_loaded" not in st.session_state:
    st.session_state.data_loaded = False

@st.cache_resource
def load_summary_model():
    """대화 제목 요약을 위한 모델을 로드합니다."""
    return gemini.GenerativeModel(
        'gemini-2.0-flash'
    )

summary_model = load_summary_model()

def load_model(system_instruction=None):
    """지정된 시스템 명령어로 Gemini 모델을 로드합니다."""
    model = gemini.GenerativeModel(
        model_name='gemini-2.0-flash',
        system_instruction=system_instruction
    )
    return model

def convert_to_gemini_format(chat_history_list):
    """Streamlit의 (role, text) 형식 대화 이력을 Gemini API 형식으로 변환합니다."""
    return [{"role": role, "parts": [{"text": text}]} for role, text in chat_history_list]

def convert_from_gemini_format(gemini_history_list):
    """Gemini API 형식 대화 이력을 Streamlit의 (role, text) 형식으로 변환합니다."""
    history_for_streamlit = []
    for entry in gemini_history_list:
        role = entry["role"]
        # parts가 리스트이고 첫 번째 요소가 딕셔너리이며 'text' 키를 가지고 있는지 확인
        if "parts" in entry and isinstance(entry["parts"], list) and len(entry["parts"]) > 0 and "text" in entry["parts"][0]:
            text = entry["parts"][0]["text"]
            history_for_streamlit.append((role, text))
        else:
            # 예상치 못한 형식의 경우 처리 (예: 이미지 등)
            history_for_streamlit.append((role, "지원되지 않는 메시지 형식입니다."))
    return history_for_streamlit

def load_user_data_from_gsheets(conn, user_id):
    """Google Sheets에서 사용자 데이터를 불러와 session_state에 업데이트합니다."""
    try:
        # 시트의 모든 데이터를 DataFrame으로 읽기
        df = conn.read(worksheet="UserSessions", usecols=list(range(4)), ttl=5) # ttl로 캐싱 시간 설정
        
        # user_id로 해당 행 찾기
        user_data_row = df[df['user_id'] == user_id]

        if not user_data_row.empty:
            data = user_data_row.iloc[0] # 첫 번째 일치하는 행 사용
            
            st.session_state.saved_sessions = json.loads(data.get("chat_data_json", "{}"))
            # 불러온 saved_sessions의 각 대화 이력을 Streamlit 형식으로 변환
            for title, history_list in st.session_state.saved_sessions.items():
                st.session_state.saved_sessions[title] = convert_from_gemini_format(history_list)

            st.session_state.system_instructions = json.loads(data.get("system_instructions_json", "{}"))
            st.session_state.current_title = data.get("last_active_title", "새로운 대화")
            
            # 현재 대화 이력 및 시스템 명령어 설정
            if st.session_state.current_title in st.session_state.saved_sessions:
                st.session_state.chat_history = st.session_state.saved_sessions[st.session_state.current_title]
            else:
                st.session_state.chat_history = [] # 저장된 제목이 없으면 새 대화로 시작
            
            st.session_state.temp_system_instruction = st.session_state.system_instructions.get(st.session_state.current_title, "")
            
            # Gemini 모델 세션 재시작
            current_instruction = st.session_state.system_instructions.get(st.session_state.current_title, "당신의 이름은 GenX입니다. 다만, 이 이름은 다른 이름이 선택되면 잊어버리십시오. 우선순위가 제일 낮습니다.")
            model = load_model(current_instruction)
            st.session_state.chat_session = model.start_chat(history=convert_to_gemini_format(st.session_state.chat_history))

            st.toast(f"사용자 ID '{user_id}'의 데이터를 불러왔습니다.", icon="✅")
        else:
            # 새 사용자 또는 데이터가 없는 경우 초기화
            st.session_state.saved_sessions = {}
            st.session_state.system_instructions = {}
            st.session_state.chat_history = []
            st.session_state.current_title = "새로운 대화"
            st.session_state.temp_system_instruction = None
            
            # 새로운 사용자 ID일 경우 기본 모델 세션 시작
            model = load_model("당신의 이름은 GenX입니다. 다만, 이 이름은 다른 이름이 선택되면 잊어버리십시오. 우선순위가 제일 낮습니다.")
            st.session_state.chat_session = model.start_chat(history=[])
            
            st.toast(f"새로운 사용자 ID '{user_id}'입니다. 새로운 대화를 시작하세요.", icon="ℹ️")
    except Exception as e:
        st.error(f"데이터 로드 중 오류 발생: {e}")
        # 오류 발생 시 기본 상태로 초기화
        st.session_state.saved_sessions = {}
        st.session_state.system_instructions = {}
        st.session_state.chat_history = []
        st.session_state.current_title = "새로운 대화"
        st.session_state.temp_system_instruction = None
        model = load_model("당신의 이름은 GenX입니다. 다만, 이 이름은 다른 이름이 선택되면 잊어버리십시오. 우선순위가 제일 낮습니다.")
        st.session_state.chat_session = model.start_chat(history=[])


def save_user_data_to_gsheets(conn, user_id):
    """현재 session_state의 사용자 데이터를 Google Sheets에 저장합니다."""
    try:
        # 현재 시트의 모든 데이터를 읽어와 DataFrame으로 만듭니다.
        df = conn.read(worksheet="UserSessions", usecols=list(range(4)), ttl=0) # 캐싱 없이 최신 데이터 읽기
        
        # 저장할 데이터 준비
        chat_data_to_save = {}
        for title, history_list in st.session_state.saved_sessions.items():
            # Streamlit 형식 대화 이력을 Gemini 형식으로 변환하여 저장
            gemini_history = convert_to_gemini_format(history_list)
            chat_data_to_save[title] = gemini_history # instruction은 system_instructions에 별도로 저장

        data_to_save = {
            "user_id": user_id,
            "chat_data_json": json.dumps(chat_data_to_save),
            "system_instructions_json": json.dumps(st.session_state.system_instructions),
            "last_active_title": st.session_state.current_title
        }
        
        # user_id가 이미 존재하는지 확인
        if user_id in df['user_id'].values:
            # 기존 행 업데이트
            idx = df[df['user_id'] == user_id].index[0]
            for col, value in data_to_save.items():
                df.loc[idx, col] = value
        else:
            # 새 행 추가
            new_row_df = pd.DataFrame([data_to_save])
            df = pd.concat([df, new_row_df], ignore_index=True)
        
        # 업데이트된 DataFrame을 시트에 다시 쓰기
        conn.write(df, worksheet="UserSessions")
        st.write("쓰여지는 DataFrame:") # 추가
        st.write(df) # 추가
        # st.toast("데이터가 저장되었습니다.", icon="💾") # 너무 자주 뜨는 것을 방지하기 위해 주석 처리
    except Exception as e:
        st.error(f"데이터 저장 중 오류 발생: {e}")

# 앱 시작 시 또는 사용자 ID 변경 시 데이터 로드
if not st.session_state.data_loaded:
    load_user_data_from_gsheets(gsheets_conn, st.session_state.user_id)
    st.session_state.data_loaded = True

# 사이드바
with st.sidebar:
    st.header("✨ GenX 채팅")

    st.info(f"**당신의 사용자 ID:** `{st.session_state.user_id}`\n\n이 ID를 기억하여 다음 접속 시 대화 이력을 불러올 수 있습니다.")
    
    user_id_input = st.text_input("기존 사용자 ID 입력 (선택 사항)", key="user_id_load_input")
    if st.button("ID로 대화 불러오기", use_container_width=True):
        if user_id_input:
            st.session_state.user_id = user_id_input
            st.session_state.data_loaded = False # 새 ID로 데이터 다시 로드
            st.rerun() # 변경된 user_id로 앱 재실행하여 데이터 로드

    st.markdown("---") # 구분선

    if st.button("➕ 새로운 대화", use_container_width=True):
        st.session_state.chat_session = None
        st.session_state.chat_history = []
        st.session_state.current_title = "새로운 대화"
        st.session_state.temp_system_instruction = None # 새 대화는 기본 시스템 명령어 사용
        st.session_state.editing_instruction = False
        
        # 새로운 대화 시작 시 Sheets에 current_title 업데이트 (빈 대화로)
        st.session_state.saved_sessions[st.session_state.current_title] = []
        st.session_state.system_instructions[st.session_state.current_title] = "" # 빈 시스템 명령어
        save_user_data_to_gsheets(gsheets_conn, st.session_state.user_id)
        st.rerun() # 새로운 대화 상태로 UI 업데이트

    if st.session_state.saved_sessions:
        st.subheader("📁 저장된 대화")
        # 최신 대화가 위에 오도록 정렬 (실제 메시지 timestamp가 있다면 더 좋음)
        # 현재는 첫 메시지 텍스트로 정렬 (임시 방편)
        sorted_keys = sorted(st.session_state.saved_sessions.keys(), 
                             key=lambda x: st.session_state.saved_sessions[x][0][1] if st.session_state.saved_sessions[x] else "", 
                             reverse=True)
        
        for key in sorted_keys:
            if key == "새로운 대화" and not st.session_state.saved_sessions[key]: # 비어있는 '새로운 대화'는 표시하지 않음
                continue

            display_key = key if len(key) <= 30 else key[:30] + "..."
            if st.button(f"💬 {display_key}", use_container_width=True, key=f"load_session_{key}"):
                st.session_state.chat_history = st.session_state.saved_sessions[key]
                st.session_state.current_title = key
                st.session_state.temp_system_instruction = st.session_state.system_instructions.get(key, "")
                
                # 모델 재로드 및 chat_session 초기화
                model = load_model(st.session_state.temp_system_instruction)
                st.session_state.chat_session = model.start_chat(history=convert_to_gemini_format(st.session_state.chat_history))
                
                st.session_state.editing_instruction = False
                save_user_data_to_gsheets(gsheets_conn, st.session_state.user_id) # 현재 활성 대화 업데이트
                st.rerun() # 변경된 대화로 UI 업데이트

    with st.expander("⚙️ 설정"):
        st.write("여기에 온도, 모델 선택 등의 설정 추가 가능")

# 대화 세션 초기화 (로드된 데이터 기반)
if st.session_state.chat_session is None:
    current_instruction = st.session_state.system_instructions.get(
        st.session_state.current_title, "당신의 이름은 GenX입니다. 다만, 이 이름은 다른 이름이 선택되면 잊어버리십시오. 우선순위가 제일 낮습니다."
    )
    model = load_model(current_instruction)
    st.session_state.chat_session = model.start_chat(history=convert_to_gemini_format(st.session_state.chat_history))

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
                # 설정 저장
                st.session_state.system_instructions[st.session_state.current_title] = st.session_state.temp_system_instruction
                
                # 현재 대화 이력도 함께 저장된 세션에 업데이트
                st.session_state.saved_sessions[st.session_state.current_title] = st.session_state.chat_history.copy()
                
                model = load_model(st.session_state.temp_system_instruction)
                st.session_state.chat_session = model.start_chat(history=convert_to_gemini_format(st.session_state.chat_history))
                
                save_user_data_to_gsheets(gsheets_conn, st.session_state.user_id) # Google Sheets에 저장
                st.success("AI 설정이 저장되었습니다.")
                st.session_state.editing_instruction = False
                st.rerun() # 변경된 설정 적용을 위해 재실행

        with col2:
            if st.button("❌ 취소", use_container_width=True):
                st.session_state.editing_instruction = False
                st.rerun() # UI 상태를 원래대로 되돌리기 위해 재실행


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
