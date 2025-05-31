import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import os
import uuid
import json
import google.generativeai as genai
from PIL import Image

# --- Configuration and Initialization ---
# Gemini API 키 설정
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Firebase Admin SDK 초기화
if not firebase_admin._apps:
    cred_json = os.environ.get("FIREBASE_CREDENTIAL_PATH")
    if cred_json:
        try:
            cred = credentials.Certificate(json.loads(cred_json))
            firebase_admin.initialize_app(cred)
            print("Firebase Admin SDK initialized.")
        except json.JSONDecodeError as e:
            st.error(f"Firebase Credential Path environment variable has invalid JSON format: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Firebase Admin SDK initialization error: {e}")
            st.stop()
    else:
        st.error("FIREBASE_CREDENTIAL_PATH environment variable is not set.")
        st.stop()

db = firestore.client()

st.set_page_config(page_title="GenX", layout="wide")

# --- Session State Initialization ---
# Stores chat history. Each element is a (role, text) tuple.
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
# Stores the chat session with Gemini API.
if "chat_session" not in st.session_state:
    st.session_state.chat_session = None
# Manages all saved chat sessions. (title: chat history)
if "saved_sessions" not in st.session_state:
    st.session_state.saved_sessions = {}
# Current active chat title.
if "current_title" not in st.session_state:
    st.session_state.current_title = "새로운 대화"
# Stores system instructions for each chat session.
if "system_instructions" not in st.session_state:
    st.session_state.system_instructions = {}
# Temporary system instruction during AI settings editing.
if "temp_system_instruction" not in st.session_state:
    st.session_state.temp_system_instruction = None
# Flag for AI settings edit mode.
if "editing_instruction" not in st.session_state:
    st.session_state.editing_instruction = False
# Current user ID.
if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())
# Flag for data loaded from Firestore.
if "data_loaded" not in st.session_state:
    st.session_state.data_loaded = False
# Flag for chat title edit mode.
if "editing_title" not in st.session_state:
    st.session_state.editing_title = False
# Temporarily stores new chat title during editing.
if "new_title" not in st.session_state:
    st.session_state.new_title = st.session_state.current_title
# Flag for AI response regeneration request.
if "regenerate_requested" not in st.session_state:
    st.session_state.regenerate_requested = False
# Stores the uploaded image file object.
if "uploaded_file" not in st.session_state:
    st.session_state.uploaded_file = None
# AI is currently generating a response.
if "is_generating" not in st.session_state:
    st.session_state.is_generating = False
# Stores the last user message to be regenerated (text and optional image)
if "last_user_input_for_regen" not in st.session_state:
    st.session_state.last_user_input_for_regen = None

# --- Helper Functions ---
# Loads model for chat title summarization (cached).
@st.cache_resource
def load_summary_model():
    return genai.GenerativeModel('gemini-2.0-flash') # Use Flash model for faster summarization

summary_model = load_summary_model()
default_system_instruction = "당신의 이름은 GenX입니다. 다만, 이 이름은 다른 이름이 선택되면 잊어버리십시오. 우선순위가 제일 낮습니다."

# Loads main chat model (cached).
def load_main_model(system_instruction=default_system_instruction):
    # Gemini 2.0 Flash supports multimodal input and is fast.
    model = genai.GenerativeModel(model_name='gemini-2.0-flash', system_instruction=system_instruction)
    return model

# Converts Streamlit chat history to Gemini API format.
def convert_to_gemini_format(chat_history_list):
    gemini_history = []
    for role, text in chat_history_list:
        # For simplicity, assuming 'text' is always the part for now.
        # If you later store image data in chat_history, this conversion needs to be more complex.
        gemini_history.append({"role": role, "parts": [{"text": text}]})
    return gemini_history

# Firestore에서 사용자 데이터를 로드합니다.
def load_user_data_from_firestore(user_id):
    try:
        sessions_ref = db.collection("user_sessions").document(user_id)
        doc = sessions_ref.get()
        if doc.exists:
            data = doc.to_dict()
            st.session_state.saved_sessions = data.get("chat_data", {})
            # Firestore에서 로드된 데이터를 (role, text) 튜플 리스트로 변환
            for title, history_list in st.session_state.saved_sessions.items():
                st.session_state.saved_sessions[title] = [(item["role"], item["text"]) for item in history_list]

            st.session_state.system_instructions = data.get("system_instructions", {})
            st.session_state.current_title = data.get("last_active_title", "새로운 대화")

            if st.session_state.current_title in st.session_state.saved_sessions:
                st.session_state.chat_history = st.session_state.saved_sessions[st.session_state.current_title]
            else:
                st.session_state.chat_history = []

            st.session_state.temp_system_instruction = st.session_state.system_instructions.get(st.session_state.current_title, "")
            current_instruction = st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)

            st.session_state.chat_session = load_main_model(current_instruction).start_chat(history=convert_to_gemini_format(st.session_state.chat_history))
            st.toast(f"Firestore에서 사용자 ID '{user_id}'의 데이터를 불러왔습니다.", icon="✅")
        else:
            st.session_state.saved_sessions = {}
            st.session_state.system_instructions = {}
            st.session_state.chat_history = []
            st.session_state.current_title = "새로운 대화"
            st.session_state.temp_system_instruction = None
            st.session_state.chat_session = load_main_model().start_chat(history=[])
            st.toast(f"Firestore에 사용자 ID '{user_id}'에 대한 데이터가 없습니다. 새로운 대화를 시작하세요.", icon="ℹ️")
    except Exception as e:
        error_message = f"Firestore에서 데이터 로드 중 오류 발생: {e}"
        print(error_message)
        st.error(error_message)
        # Fallback to empty state on error
        st.session_state.saved_sessions = {}
        st.session_state.system_instructions = {}
        st.session_state.chat_history = []
        st.session_state.current_title = "새로운 대화"
        st.session_state.temp_system_instruction = None
        st.session_state.chat_session = load_main_model().start_chat(history=[])

# Firestore에 사용자 데이터를 저장합니다.
def save_user_data_to_firestore(user_id):
    try:
        sessions_ref = db.collection("user_sessions").document(user_id)
        chat_data_to_save = {}
        for title, history_list in st.session_state.saved_sessions.items():
            # Convert (role, text) tuple to dictionary for Firestore storage
            chat_data_to_save[title] = [{"role": item[0], "text": item[1]} for item in history_list]

        data_to_save = {
            "chat_data": chat_data_to_save,
            "system_instructions": st.session_state.system_instructions,
            "last_active_title": st.session_state.current_title
        }
        sessions_ref.set(data_to_save)
        print(f"User data for ID '{user_id}' saved to Firestore.")
    except Exception as e:
        error_message = f"Error saving data to Firestore: {e}"
        print(error_message)
        st.error(error_message)

# --- App Logic Execution Flow ---
# Load user data on app start
if not st.session_state.data_loaded:
    load_user_data_from_firestore(st.session_state.user_id)
    st.session_state.data_loaded = True

# Initialize chat session if it doesn't exist
if st.session_state.chat_session is None:
    current_instruction = st.session_state.system_instructions.get(
        st.session_state.current_title, default_system_instruction
    )
    st.session_state.chat_session = load_main_model(current_instruction).start_chat(history=convert_to_gemini_format(st.session_state.chat_history))

# --- Sidebar UI ---
with st.sidebar:
    st.header("✨ GenX 채팅")

    with st.expander("🔑 사용자 ID 관리", expanded=False):
        st.info(f"**당신의 사용자 ID:** `{st.session_state.user_id}`\n\n이 ID를 기억하여 다음 접속 시 대화 이력을 불러올 수 있습니다.")
        user_id_input = st.text_input("기존 사용자 ID 입력 (선택 사항)", key="user_id_load_input")
        if st.button("ID로 대화 불러오기", use_container_width=True, disabled=st.session_state.is_generating):
            if user_id_input:
                st.session_state.user_id = user_id_input
                st.session_state.data_loaded = False # Force reload
                st.rerun()

    st.markdown("---")

    if st.button("➕ 새로운 대화", use_container_width=True, disabled=st.session_state.is_generating):
        st.session_state.chat_session = None # Reset chat session
        st.session_state.chat_history = []
        st.session_state.current_title = "새로운 대화"
        st.session_state.temp_system_instruction = None
        st.session_state.editing_instruction = False
        st.session_state.saved_sessions[st.session_state.current_title] = [] # Add new empty session
        st.session_state.system_instructions[st.session_state.current_title] = default_system_instruction
        save_user_data_to_firestore(st.session_state.user_id)
        st.rerun()

    if st.session_state.saved_sessions:
        st.subheader("📁 저장된 대화")
        # Sort sessions by last message time (if available) or title
        sorted_keys = sorted(st.session_state.saved_sessions.keys(),
                             key=lambda x: st.session_state.saved_sessions[x][-1][1] if st.session_state.saved_sessions[x] else "",
                             reverse=True)
        for key in sorted_keys:
            if key == "새로운 대화" and not st.session_state.saved_sessions[key]:
                continue # Do not display empty "New Conversation" sessions
            display_key = key if len(key) <= 30 else key[:30] + "..."
            if st.button(f"💬 {display_key}", use_container_width=True, key=f"load_session_{key}", disabled=st.session_state.is_generating):
                st.session_state.chat_history = st.session_state.saved_sessions[key]
                st.session_state.current_title = key
                st.session_state.new_title = key # Initial value for title editing
                st.session_state.temp_system_instruction = st.session_state.system_instructions.get(key, default_system_instruction)
                
                # Reinitialize chat session with loaded history
                current_instruction = st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)
                st.session_state.chat_session = load_main_model(current_instruction).start_chat(history=convert_to_gemini_format(st.session_state.chat_history))

                st.session_state.editing_instruction = False
                st.session_state.editing_title = False
                save_user_data_to_firestore(st.session_state.user_id)
                st.rerun()

    with st.expander("⚙️ 설정"):
        st.write("여기에 온도, 모델 선택 등의 설정 추가 가능")

# --- Main Content Area ---
# Display current conversation title and edit options
col1, col2 = st.columns([0.9, 0.1])
with col1:
    if not st.session_state.editing_title:
        st.subheader(f"💬 {st.session_state.current_title}")
    else:
        st.text_input("새로운 제목", key="new_title_input", value=st.session_state.new_title, label_visibility="collapsed")
with col2:
    if not st.session_state.editing_title:
        if st.button("✏️", key="edit_title_button", help="대화 제목 수정", disabled=st.session_state.is_generating):
            st.session_state.editing_title = True
            st.session_state.new_title = st.session_state.current_title
            st.rerun()
    else:
        if st.button("✅", key="save_title_button", help="새로운 제목 저장", disabled=st.session_state.is_generating):
            new_title = st.session_state.new_title_input
            if new_title and new_title != st.session_state.current_title:
                if st.session_state.current_title in st.session_state.saved_sessions:
                    st.session_state.saved_sessions[new_title] = st.session_state.saved_sessions.pop(st.session_state.current_title)
                    st.session_state.system_instructions[new_title] = st.session_state.system_instructions.pop(st.session_state.current_title)
                    st.session_state.current_title = new_title
                    save_user_data_to_firestore(st.session_state.user_id)
                    st.toast(f"대화 제목이 '{st.session_state.current_title}'로 변경되었습니다.", icon="📝")
                else:
                    st.warning("이전 대화 제목을 찾을 수 없습니다. 저장 후 다시 시도해주세요.")
            st.session_state.editing_title = False
            st.rerun()
        if st.button("❌", key="cancel_title_button", help="제목 수정 취소", disabled=st.session_state.is_generating):
            st.session_state.editing_title = False
            st.rerun()

# AI settings button and area
if st.button("⚙️ AI 설정하기", help="시스템 명령어를 설정할 수 있어요", disabled=st.session_state.is_generating):
    st.session_state.editing_instruction = not st.session_state.editing_instruction

if st.session_state.editing_instruction:
    with st.expander("🧠 시스템 명령어 설정", expanded=True):
        st.session_state.temp_system_instruction = st.text_area(
            "System instruction 입력",
            value=st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction),
            height=200,
            key="system_instruction_editor",
            disabled=st.session_state.is_generating
        )
        _, col1_ai, col2_ai = st.columns([0.9, 0.3, 0.3])
        with col1_ai:
            if st.button("✅ 저장", use_container_width=True, key="save_instruction_button", disabled=st.session_state.is_generating):
                st.session_state.system_instructions[st.session_state.current_title] = st.session_state.temp_system_instruction
                st.session_state.saved_sessions[st.session_state.current_title] = st.session_state.chat_history.copy()
                
                current_instruction = st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)
                st.session_state.chat_session = load_main_model(current_instruction).start_chat(history=convert_to_gemini_format(st.session_state.chat_history))
                
                save_user_data_to_firestore(st.session_state.user_id)
                st.success("AI 설정이 저장되었습니다.")
                st.session_state.editing_instruction = False
                st.rerun()
        with col2_ai:
            if st.button("❌ 취소", use_container_width=True, key="cancel_instruction_button", disabled=st.session_state.is_generating):
                st.session_state.editing_instruction = False
                st.rerun()

# --- Chat Display Area ---
# Container to display all chat messages
chat_display_container = st.container()

# --- Final Chat History Display (Always Rendered) ---
# This ensures all messages are displayed correctly.
with chat_display_container:
    for i, (role, message) in enumerate(st.session_state.chat_history):
        with st.chat_message("ai" if role == "model" else "user"):
            st.markdown(message)
            # Display regenerate button only on the last AI message if not currently generating
            if role == "model" and i == len(st.session_state.chat_history) - 1 and not st.session_state.is_generating:
                if st.button("🔄 다시 생성", key=f"regenerate_button_final_{i}", use_container_width=True):
                    st.session_state.regenerate_requested = True
                    st.session_state.is_generating = True # Disable input during regeneration
                    st.session_state.chat_history.pop() # Remove last AI message before regeneration
                    # No need to rewind chat_session here, it will be reinitialized in the regeneration block
                    st.rerun()

# --- Input Area ---
# Place st.chat_input and file uploader on the same line
col_prompt_input, col_upload_icon = st.columns([0.85, 0.15]) # Adjust column ratio for better spacing

with col_prompt_input:
    # st.chat_input handles Enter key submission automatically.
    user_prompt = st.chat_input("메시지를 입력하세요.", key="user_prompt_input", disabled=st.session_state.is_generating)

with col_upload_icon:
    # Make the image upload button look like an icon.
    uploaded_file_for_submit = st.file_uploader("🖼️", type=["png", "jpg", "jpeg"], key="file_uploader_main", label_visibility="collapsed", disabled=st.session_state.is_generating, help="이미지 파일을 업로드하세요.")

# Update uploaded_file state immediately upon file selection
if uploaded_file_for_submit:
    st.session_state.uploaded_file = uploaded_file_for_submit
    st.caption("이미지 업로드 완료")
else:
    # If user removes the file from the uploader, reset session state as well
    if st.session_state.uploaded_file is not None:
        st.session_state.uploaded_file = None

# --- Regeneration Logic ---
# This block runs only when regeneration is requested.
if st.session_state.regenerate_requested:
    st.session_state.is_generating = True # Set generation flag to True
    
    # Get the previous user message (which is now the last message after pop() in the button handler)
    previous_user_message_content = st.session_state.last_user_input_for_regen["text"]
    previous_user_image_data = st.session_state.last_user_input_for_regen["image"]
    previous_user_image_mime = st.session_state.last_user_input_for_regen["mime_type"]

    with chat_display_container: # Display regenerated message within the chat area
        # The user message is already displayed by the main history loop
        with st.chat_message("ai"):
            message_placeholder = st.empty()
            full_response = ""
            try:
                # Reinitialize chat_session with history up to the previous user message.
                current_instruction = st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)
                # The history for the chat session should exclude the user message that is being regenerated.
                # It should only contain the conversation up to the turn *before* the user's last input.
                st.session_state.chat_session = load_main_model(current_instruction).start_chat(history=convert_to_gemini_format(st.session_state.chat_history[:-1]))

                regen_contents = [previous_user_message_content]
                if previous_user_image_data:
                    regen_contents.append({"inline_data": {"mime_type": previous_user_image_mime, "data": previous_user_image_data}})

                response_stream = st.session_state.chat_session.send_message(regen_contents, stream=True)
                
                for chunk in response_stream:
                    full_response += chunk.text
                    message_placeholder.markdown(full_response + "▌")
                message_placeholder.markdown(full_response) # Final display without cursor

                st.session_state.chat_history.append(("model", full_response)) # Add new AI message
                st.session_state.regenerate_requested = False
                st.session_state.is_generating = False # Reset generation flag
                
                # Save data to Firestore after successful regeneration
                st.session_state.saved_sessions[st.session_state.current_title] = st.session_state.chat_history.copy()
                current_instruction_for_save = st.session_state.temp_system_instruction if st.session_state.temp_system_instruction is not None else st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)
                st.session_state.system_instructions[st.session_state.current_title] = current_instruction_for_save
                save_user_data_to_firestore(st.session_state.user_id)

            except Exception as e:
                st.error(f"Regeneration error: {e}")
                message_placeholder.markdown("죄송합니다. 다시 생성하는 중 오류가 발생했습니다.")
                st.session_state.regenerate_requested = False # Reset flag on error
                st.session_state.is_generating = False # Reset flag on error
            finally:
                st.rerun() # Rerun UI after regeneration/error

# AI generation trigger logic
# Trigger if user_prompt is entered (Enter key) OR if an image is uploaded and user_prompt is empty
if user_prompt is not None and not st.session_state.is_generating:
    if user_prompt != "" or st.session_state.uploaded_file is not None:
        st.session_state.chat_history.append(("user", user_prompt)) # Add prompt (can be empty string)
        st.session_state.is_generating = True
        # Store the current user input (text and image) for potential regeneration
        st.session_state.last_user_input_for_regen = {
            "text": user_prompt,
            "image": st.session_state.uploaded_file.getvalue() if st.session_state.uploaded_file else None,
            "mime_type": st.session_state.uploaded_file.type if st.session_state.uploaded_file else None
        }
        st.rerun() # Update UI and start generation immediately after prompt submission

# --- AI Response Generation and Display Logic ---
# This block runs only when AI is generating a response (and not regenerating).
if st.session_state.is_generating and not st.session_state.regenerate_requested:
    with chat_display_container: # Display generating message within the chat area
        # The user message is already displayed by the main history loop
        with st.chat_message("ai"):
            message_placeholder = st.empty() # Placeholder for streaming response
            full_response = ""
            try:
                # Reinitialize chat_session with the history up to the current user message.
                current_instruction = st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)
                st.session_state.chat_session = load_main_model(current_instruction).start_chat(history=convert_to_gemini_format(st.session_state.chat_history[:-1])) # Exclude the very last user message for history initialization

                contents = [st.session_state.chat_history[-1][1]] # Current user prompt
                if st.session_state.uploaded_file:
                    image_bytes = st.session_state.uploaded_file.getvalue()
                    image_part = {"inline_data": {"mime_type": st.session_state.uploaded_file.type, "data": image_bytes}}
                    contents.append(image_part)

                # Send content to the model using the reinitialized chat_session
                response_stream = st.session_state.chat_session.send_message(contents, stream=True)
                
                for chunk in response_stream:
                    full_response += chunk.text
                    message_placeholder.markdown(full_response + "▌") # Add blinking cursor for streaming
                message_placeholder.markdown(full_response) # Final display without cursor
                
                st.session_state.chat_history.append(("model", full_response))
                st.session_state.uploaded_file = None # Reset uploaded file after processing
                st.session_state.is_generating = False # Reset generation flag
                
                # Auto-generate title for new conversations on first interaction
                if st.session_state.current_title == "새로운 대화" and len(st.session_state.chat_history) == 2:
                    with st.spinner("대화 제목 생성 중..."):
                        try:
                            summary_prompt_text = st.session_state.chat_history[-2][1] # 사용자 프롬프트 가져오기
                            # Note: uploaded_file is already None here, so we rely on chat_history text.
                            summary = summary_model.generate_content(f"다음 사용자의 메시지를 요약해서 대화 제목으로 만들어줘 (한 문장, 30자 이내):\n\n{summary_prompt_text}")
                            original_title = summary.text.strip().replace("\n", " ").replace('"', '')
                        except Exception as e:
                            st.warning(f"Title generation error: {e}. Using default title.")
                            original_title = "새로운 대화"

                        title_key = original_title
                        count = 1
                        while title_key in st.session_state.saved_sessions:
                            title_key = f"{original_title} ({count})"
                            count += 1
                        st.session_state.current_title = title_key
                        st.toast(f"대화 제목이 '{title_key}'로 설정되었습니다.", icon="📝")

                # Save data to Firestore after successful generation
                st.session_state.saved_sessions[st.session_state.current_title] = st.session_state.chat_history.copy()
                current_instruction_for_save = st.session_state.temp_system_instruction if st.session_state.temp_system_instruction is not None else st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)
                st.session_state.system_instructions[st.session_state.current_title] = current_instruction_for_save
                save_user_data_to_firestore(st.session_state.user_id)

            except Exception as e:
                st.error(f"Message generation error: {e}")
                message_placeholder.markdown("죄송합니다. 메시지를 처리하는 중 오류가 발생했습니다.")
                st.session_state.is_generating = False # Reset flag on error
            finally:
                st.rerun() # Rerun UI after generation/error

