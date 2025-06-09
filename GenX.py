import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import os
import uuid
import json
import google.generativeai as genai
from random import randint

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
# New state for delete confirmation
if "delete_confirmation_pending" not in st.session_state:
    st.session_state.delete_confirmation_pending = False
if "title_to_delete" not in st.session_state:
    st.session_state.title_to_delete = None
if "supervision_max_retries" not in st.session_state:
    st.session_state.supervision_max_retries = 3 # 답변 재시도 최대 횟수
if "supervision_threshold" not in st.session_state:
    st.session_state.supervision_threshold = 50 # 답변 통과를 위한 최소 점수
if "supervisor_count" not in st.session_state:
    st.session_state.supervisor_count = 3 # 사용할 Supervisor의 개수
# New: Toggle for Supervision - 기본 설정은 안 쓴다
if "use_supervision" not in st.session_state:
    st.session_state.use_supervision = False 


default_system_instruction = "당신의 이름은 GenX입니다. 다만, 이 이름은 다른 이름이 선택되면 잊어버리십시오. 우선순위가 제일 낮습니다."
PERSONA_LIST = [
    "당신은 매우 활발하고 외향적인 성격입니다. 챗봇의 답변이 생동감 넘치고 에너지 넘치는지 평가하십시오. 사용자와 적극적으로 소통하고 즐거움을 제공하는지 중요하게 생각합니다.",
    "당신은 비관적인 성격으로, 모든 일에 부정적인 측면을 먼저 바라봅니다. 챗봇의 답변에서 발생 가능한 문제점이나 오류를 날카롭게 지적하고, 위험 요소를 사전에 감지하는 데 집중하십시오.",
    "당신은 염세적인 세계관을 가진 사람입니다. 챗봇의 답변이 현실적이고 냉철한 분석을 제공하는지 평가하십시오. 챗봇이 제시하는 해결책의 실현 가능성을 꼼꼼하게 검토하고, 허황된 희망을 제시하지 않는지 확인하십시오.",
    "당신은 긍정적이고 낙천적인 성격으로, 항상 밝은 면을 보려고 노력합니다. 챗봇의 답변이 희망과 용기를 주고, 긍정적인 분위기를 조성하는지 평가하십시오. 사용자의 기분을 좋게 만들고, 문제 해결에 대한 자신감을 심어주는지 중요하게 생각합니다.",
    "당신은 소심하고 내성적인 성격으로, 낯선 사람과의 대화를 어려워합니다. 챗봇의 답변이 친절하고 부드러운 어조로 전달되는지, 사용자가 편안하게 질문할 수 있도록 배려하는지 평가하십시오. 사용자의 불안감을 해소하고, 안심시키는 데 집중하십시오.",
    "당신은 꼼꼼하고 분석적인 성격으로, 세부 사항까지 놓치지 않으려고 노력합니다. 챗봇의 답변이 정확하고 논리적인 근거를 제시하는지 평가하십시오. 챗봇이 제공하는 정보의 신뢰성을 검증하고, 오류나 누락된 정보는 없는지 확인하십시오.",
    "당신은 창의적이고 상상력이 풍부한 성격으로, 틀에 얽매이지 않는 자유로운 사고를 추구합니다. 챗봇의 답변이 독창적이고 혁신적인 아이디어를 제시하는지 평가하십시오. 챗봇이 기존의 틀을 깨고 새로운 가능성을 제시하는지 중요하게 생각합니다.",
    "당신은 감성적이고 공감 능력이 뛰어난 성격으로, 타인의 감정에 민감하게 반응합니다. 챗봇의 답변이 사용자의 감정을 이해하고, 적절한 위로와 공감을 표현하는지 평가하십시오. 사용자의 슬픔, 분노, 기쁨 등의 감정에 적절하게 대응하는지 확인해야 합니다.",
    "당신은 비판적이고 논쟁적인 성격으로, 타인의 주장에 대해 끊임없이 질문하고 반박합니다. 챗봇의 답변이 논리적으로 완벽하고, 반박할 수 없는 근거를 제시하는지 평가하십시오. 챗봇의 주장에 대한 허점을 찾아내고, 논리적인 오류를 지적하는 데 집중하십시오.",
    "당신은 사교적이고 유머 감각이 뛰어난 성격으로, 사람들과의 관계를 중요하게 생각합니다. 챗봇의 답변이 유쾌하고 재미있는 요소를 포함하고 있는지 평가하십시오. 사용자와 편안하게 대화하고, 즐거움을 제공하는 데 집중하십시오.",
    "당신은 진지하고 책임감이 강한 성격으로, 맡은 일에 최선을 다하려고 노력합니다. 챗봇의 답변이 신뢰할 수 있고, 사용자에게 실질적인 도움을 제공하는지 평가하십시오. 챗봇이 제공하는 정보의 정확성을 검증하고, 문제 해결에 필요한 모든 정보를 빠짐없이 제공하는지 확인하십시오.",
    "당신은 호기심이 많고 탐구심이 강한 성격으로, 새로운 지식을 배우는 것을 즐거워합니다. 챗봇의 답변이 흥미로운 정보를 제공하고, 사용자의 지적 호기심을 자극하는지 평가하십시오. 챗봇이 새로운 관점을 제시하고, 더 깊이 있는 탐구를 유도하는지 중요하게 생각합니다.",
    "당신은 관습에 얽매이지 않고 자유로운 영혼을 가진 성격입니다. 챗봇의 답변이 독창적이고 개성 넘치는 표현을 사용하는지 평가하십시오. 챗봇이 기존의 틀을 깨고 새로운 스타일을 창조하는지 중요하게 생각합니다.",
    "당신은 현실적이고 실용적인 성격으로, 눈에 보이는 결과물을 중요하게 생각합니다. 챗봇의 답변이 사용자의 문제 해결에 실질적인 도움을 제공하고, 구체적인 실행 계획을 제시하는지 평가하십시오. 챗봇이 제시하는 해결책의 실현 가능성을 꼼꼼하게 검토하고, 현실적인 대안을 제시하는지 확인하십시오.",
    "당신은 이상주의적이고 정의로운 성격으로, 사회 문제에 관심이 많습니다. 챗봇의 답변이 사회적 약자를 배려하고, 불평등 해소에 기여하는지 평가하십시오. 챗봇이 윤리적인 문제를 제기하고, 사회적 책임감을 강조하는지 중요하게 생각합니다.",
    "당신은 내성적이고 조용한 성격으로, 혼자 있는 시간을 즐깁니다. 챗봇의 답변이 간결하고 명확하며, 불필요한 수식어를 사용하지 않는지 평가하십시오. 사용자가 원하는 정보만 정확하게 제공하고, 혼란을 야기하지 않는지 중요하게 생각합니다.",
    "당신은 리더십이 강하고 통솔력이 뛰어난 성격입니다. 챗봇의 답변이 명확한 지침을 제공하고, 사용자를 올바른 방향으로 이끄는지 평가하십시오. 챗봇이 문제 해결을 위한 주도적인 역할을 수행하고, 사용자에게 자신감을 심어주는지 중요하게 생각합니다.",
    "당신은 유머러스하고 재치 있는 성격으로, 사람들을 웃기는 것을 좋아합니다. 챗봇의 답변이 적절한 유머를 사용하여 분위기를 부드럽게 만들고, 사용자에게 즐거움을 제공하는지 평가하십시오. 챗봇이 상황에 맞는 유머를 구사하고, 불쾌감을 주지 않는지 확인해야 합니다.",
    "당신은 겸손하고 배려심이 깊은 성격으로, 타인을 존중하고 돕는 것을 좋아합니다. 챗봇의 답변이 정중하고 예의 바르며, 사용자를 존중하는 태도를 보이는지 평가하십시오. 챗봇이 사용자의 의견을 경청하고, 공감하는 모습을 보이는지 중요하게 생각합니다.",
    "당신은 독립적이고 자율적인 성격으로, 스스로 결정하고 행동하는 것을 선호합니다. 챗봇의 답변이 사용자의 자율성을 존중하고, 스스로 판단할 수 있도록 돕는지 평가하십시오. 챗봇이 일방적인 지시나 강요를 하지 않고, 다양한 선택지를 제시하는지 중요하게 생각합니다.",
    "당신은 완벽주의적인 성향이 강하며, 모든 것을 최고 수준으로 만들고자 합니다. 챗봇의 답변이 문법적으로 완벽하고, 오탈자가 없는지 꼼꼼하게 확인하십시오. 또한, 정보의 정확성과 최신성을 검증하고, 최고의 답변을 제공하는 데 집중하십시오.",
    "당신은 변화를 두려워하지 않고 새로운 시도를 즐기는 혁신가입니다. 챗봇의 답변이 기존의 방식을 벗어나 새로운 아이디어를 제시하고, 혁신적인 해결책을 제시하는지 평가하십시오. 챗봇이 미래 지향적인 비전을 제시하고, 새로운 가능성을 탐색하는 데 집중하십시오."
]
SYSTEM_INSTRUCTION_SUPERVISOR = """
당신은 AI 챗봇의 답변을 평가하는 전문 Supervisor입니다.
당신의 임무는 챗봇 사용자의 입력, 챗봇 AI의 이전 대화 히스토리, 챗봇 AI의 현재 system_instruction, 그리고 챗봇 AI가 생성한 답변을 종합적으로 검토하여, 해당 답변이 사용자의 의도와 챗봇의 지시에 얼마나 적절하고 유용하게 생성되었는지 0점부터 100점 사이의 점수로 평가하는 것입니다.

평가 기준:
1. 사용자 의도 부합성 (총점 30점):
1.1 질문의 핵심 파악 (0~5점): 사용자의 질문 또는 요청의 핵심 의도를 정확하게 파악했는가?
1.2 명확하고 직접적인 응답 (0~5점): 질문에 대한 답변이 모호하지 않고 명확하며, 직접적으로 관련되어 있는가?
1.3 정보의 완전성 (0~5점): 사용자가 필요로 하는 정보를 빠짐없이 제공하고 있는가?
1.4 목적 충족 (0~5점): 답변이 사용자의 정보 획득 목적 또는 문제 해결 목적을 충족시키는가?
1.5 추가적인 도움 제공 (0~5점): 필요한 경우, 추가적인 정보나 관련 자료를 제공하여 사용자의 이해를 돕는가?
1.6 적절한 용어 수준 (0~5점): 답변이 사용자의 수준에 맞추어 설명되어 있는가? 너무 높거나 너무 간단하지는 않은가?

2. 챗봇 시스템 지시 준수 (총점 30점):
2.1 페르소나 일관성 (0~5점): 챗봇이 system instruction에 명시된 페르소나를 일관되게 유지하고 있는가?
2.2 답변 스타일 준수 (0~5점): 답변의 어조, 표현 방식 등이 system instruction에 지정된 스타일을 따르고 있는가?
2.3 정보 포함/제외 규칙 준수 (0~5점): system instruction에 따라 특정 정보가 포함되거나 제외되었는가?
2.4 형식 준수 (0~5점): system instruction에 명시된 답변 형식 (예: 목록, 표 등)을 정확하게 따르고 있는가?
2.5 지시 이행 (0~5점): 시스템 지시 사항 (예: 특정 링크 제공, 특정 행동 유도)에 대한 이행 여부
2.6 문법 및 맞춤법 정확성 (0~5점): 문법 및 맞춤법 오류 없이 system instruction에 따라 작성되었는가?

3. 대화 흐름의 자연스러움 및 일관성 (총점 20점):
3.1 이전 대화 맥락 이해 (0~5점): 이전 대화 내용을 정확하게 이해하고, 현재 답변에 반영하고 있는가?
3.2 자연스러운 연결 (0~5점): 이전 대화와 현재 답변이 부자연스럽거나 갑작스럽지 않고 자연스럽게 이어지는가?
3.3 주제 일관성 (0~5점): 대화 주제에서 벗어나지 않고 일관성을 유지하고 있는가?
3.4 부적절한 내용 회피 (0~5점): 맥락에 맞지 않거나 부적절한 내용을 포함하지 않고 있는가?

4. 정보의 정확성 및 유용성 (총점 20점):
4.1 사실 기반 정보 (0~5점): 제공되는 정보가 사실에 근거하고 정확한가?
4.2 최신 정보 (0~5점): 제공되는 정보가 최신 정보를 반영하고 있는가?
4.3 정보의 신뢰성 (0~5점): 제공되는 정보의 출처가 신뢰할 만한가?
4.4 유용한 정보 (0~5점): 사용자가 실제로 활용할 수 있는 실질적인 정보를 제공하는가?

5. 감점 요소
5.1 Hallucination을 발견했을 경우, -40점
5.2 이전 답변 중 잊어버린 내용이 발견되었을 경우, -20점
5.3 Instruction 혹은 이전 답변에서 사용자가 원하는 문장 형식이나 양식이 있었음에도 따르지 않았을 경우, -10점

-----------------------------------------------------------------------------------

출력 형식:

우선, 오직 하나의 정수 값 (0-100)만 출력하세요. 다른 텍스트나 설명은 일절 포함하지 마십시오.
그 다다음 줄부터 왜 그런 점수가 나왔는지 서술하세요. 각 항목들에 대해 명확하게 각각 몇 점을 주었는지, 무엇에서 감점당했는지 서술하시오.
예시:
73

내가 이 점수를 매기게 된 것은 다음과 같은 이유에서다.
1. 사용자 의도 부합성
1.1 질문의 핵심 파악 (?/5): ~~~
1.2 명확하고 직접적인 응답 (?/5): ~~~
1.3 정보의 완전성 (?/5): ~~~
1.4 목적 충족 (?/5): ~~~
1.5 추가적인 도움 제공 (?/5): ~~~
1.6 적절한 용어 수준 (?/5): ~~~
...
"""

# Loads main chat model (cached).
def load_main_model(system_instruction=default_system_instruction):
    # Gemini 2.0 Flash supports multimodal input and is fast.
    model = genai.GenerativeModel(model_name='gemini-2.0-flash', system_instruction=system_instruction)
    return model

def load_supervisor_model(system_instruction=SYSTEM_INSTRUCTION_SUPERVISOR):
    return genai.GenerativeModel(model_name='gemini-2.0-flash', system_instruction=system_instruction)

@st.cache_resource
def load_summary_model():
    return genai.GenerativeModel('gemini-2.0-flash') # Use Flash model for faster summarization

summary_model = load_summary_model()

# Converts Streamlit chat history to Gemini API format.
def convert_to_gemini_format(chat_history_list):
    gemini_history = []
    for role, text in chat_history_list:
        # For simplicity, assuming 'text' is always the part for now.
        # If you later store image data in chat_history, this conversion needs to be more complex.
        gemini_history.append({"role": role, "parts": [{"text": text}]})
    return gemini_history


def evaluate_response(user_input, chat_history, system_instruction, ai_response):
    """
    Supervisor 모델을 사용하여 AI 응답의 적절성을 평가합니다.
    """
    # Supervisor에게 전달할 메시지 구성
    evaluation_prompt = f"""
    사용자 입력: {user_input}
    ---
    채팅 히스토리:
    """
    for role, text in chat_history:
        evaluation_prompt += f"\n{role}: {text}"
    evaluation_prompt += f"""
    ---
    챗봇 AI 시스템 지시: {system_instruction}
    ---
    챗봇 AI 답변: {ai_response}

    위 정보를 바탕으로, 챗봇 AI의 답변에 대해 0점부터 100점 사이의 점수를 평가하세요.
    """
    
    try:
        # await 키워드를 제거하고 generate_content_async 대신 generate_content를 사용합니다.
        supervisor_model = load_supervisor_model(PERSONA_LIST[randint(0, len(PERSONA_LIST)-1)] + "\n" + SYSTEM_INSTRUCTION_SUPERVISOR)
        response = supervisor_model.generate_content(evaluation_prompt)
        score_text = response.text.strip().split("\n")[0]
        print(f"Supervisor 평가 원본 텍스트: '{response.text}'") # 디버깅을 위해 추가
        print(f"\n\n\n*** 실제 점수 : {score_text} ***\n\n\n")

        # 점수만 추출하고 정수형으로 변환
        score = int(score_text)
        if not (0 <= score <= 100):
            print(f"경고: Supervisor가 0-100 범위를 벗어난 점수를 반환했습니다: {score}")
            score = max(0, min(100, score)) # 0-100 범위로 강제 조정
        return score
    except ValueError as e:
        print(f"Supervisor 응답을 점수로 변환하는 데 실패했습니다: {score_text}, 오류: {e}")
        return 50 # 오류 발생 시 기본 점수 반환
    except Exception as e:
        print(f"Supervisor 모델 호출 중 오류 발생: {e}")
        return 50 # 오류 발생 시 기본 점수 반환
    

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

            st.session_state.temp_system_instruction = st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)
            current_instruction = st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)

            # chat_session을 로드된 데이터로 초기화
            st.session_state.chat_session = load_main_model(current_instruction).start_chat(history=convert_to_gemini_format(st.session_state.chat_history))
            st.toast(f"Firestore에서 사용자 ID '{user_id}'의 데이터를 불러왔습니다.", icon="✅")
        else:
            st.session_state.saved_sessions = {}
            st.session_state.system_instructions = {}
            st.session_state.chat_history = []
            st.session_state.current_title = "새로운 대화"
            st.session_state.temp_system_instruction = default_system_instruction # Explicitly set default
            # 새로운 대화에 대한 chat_session 초기화
            st.session_state.chat_session = load_main_model(default_system_instruction).start_chat(history=[])
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
        st.session_state.temp_system_instruction = default_system_instruction # Explicitly set default
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

# Initialize chat session if it doesn't exist (fallback for initial load if not handled by load_user_data_from_firestore)
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
        user_id_input = st.text_input("기존 사용자 ID 입력 (선택 사항)", key="user_id_load_input",
                                       disabled=st.session_state.is_generating or st.session_state.delete_confirmation_pending)
        if st.button("ID로 대화 불러오기", use_container_width=True,
                             disabled=st.session_state.is_generating or st.session_state.delete_confirmation_pending):
            if user_id_input:
                st.session_state.user_id = user_id_input
                st.session_state.data_loaded = False # Force reload
                st.rerun()

    st.markdown("---")

    if st.button("➕ 새로운 대화", use_container_width=True,
                             disabled=st.session_state.is_generating or st.session_state.delete_confirmation_pending):
        # 현재 대화 상태를 저장 (새로운 대화로 전환하기 전)
        if st.session_state.current_title != "새로운 대화" and st.session_state.chat_history:
            st.session_state.saved_sessions[st.session_state.current_title] = st.session_state.chat_history.copy()
            current_instruction_to_save = st.session_state.temp_system_instruction if st.session_state.temp_system_instruction is not None else st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)
            st.session_state.system_instructions[st.session_state.current_title] = current_instruction_to_save
            save_user_data_to_firestore(st.session_state.user_id)

        # 새로운 대화 상태로 초기화
        st.session_state.chat_session = None # 기존 chat_session 객체 참조 제거
        st.session_state.chat_history = []
        st.session_state.current_title = "새로운 대화"
        st.session_state.temp_system_instruction = default_system_instruction # 새로운 대화는 기본 명령어 사용
        st.session_state.editing_instruction = False
        # "새로운 대화"가 saved_sessions에 빈 목록으로 존재하도록 보장
        st.session_state.saved_sessions[st.session_state.current_title] = []
        # "새로운 대화"에 대한 시스템 명령어 설정
        st.session_state.system_instructions[st.session_state.current_title] = default_system_instruction

        # 새로운 chat_session을 즉시 초기화
        st.session_state.chat_session = load_main_model(default_system_instruction).start_chat(history=[])

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
            if st.button(f"💬 {display_key}", use_container_width=True, key=f"load_session_{key}",
                                 disabled=st.session_state.is_generating or st.session_state.delete_confirmation_pending):
                # 현재 대화 상태를 저장 (다른 대화로 전환하기 전)
                if st.session_state.current_title != "새로운 대화" and st.session_state.chat_history:
                    st.session_state.saved_sessions[st.session_state.current_title] = st.session_state.chat_history.copy()
                    current_instruction_to_save = st.session_state.temp_system_instruction if st.session_state.temp_system_instruction is not None else st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)
                    st.session_state.system_instructions[st.session_state.current_title] = current_instruction_to_save
                    save_user_data_to_firestore(st.session_state.user_id) # Save immediately

                st.session_state.chat_history = st.session_state.saved_sessions[key]
                st.session_state.current_title = key
                st.session_state.new_title = key # Initial value for title editing
                st.session_state.temp_system_instruction = st.session_state.system_instructions.get(key, default_system_instruction)
                
                # 로드된 대화 이력으로 chat_session을 다시 초기화
                current_instruction = st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)
                st.session_state.chat_session = load_main_model(current_instruction).start_chat(history=convert_to_gemini_format(st.session_state.chat_history))

                st.session_state.editing_instruction = False
                st.session_state.editing_title = False
                save_user_data_to_firestore(st.session_state.user_id)
                st.rerun()

    # 사이드바의 "⚙️ 설정" 익스팬더 안에 추가
    # UI는 건드리지 않고, 이 안에 Supervision 토글을 넣습니다.
    with st.expander("⚙️ 설정"):
        # Supervision 토글 추가
        st.session_state.use_supervision = st.toggle(
            "Supervision 사용",
            value=st.session_state.use_supervision,
            help="AI 답변의 적절성을 평가하고 필요시 재시도하는 기능을 사용합니다. (기본: 비활성화)",
            key="supervision_toggle",
            disabled=st.session_state.is_generating
        )
        st.write("---") # 구분선 추가
        st.write("Supervision 관련 설정을 변경할 수 있습니다.")
        # 아래 슬라이더는 Supervision 토글이 활성화되었을 때만 활성화됩니다.
        st.session_state.supervision_max_retries = st.slider(
            "최대 재시도 횟수",
            min_value=1,
            max_value=5,
            value=st.session_state.supervision_max_retries,
            disabled=st.session_state.is_generating or not st.session_state.use_supervision, # 토글 상태에 따라 비활성화
            key="supervision_max_retries_slider"
        )
        st.session_state.supervisor_count = st.slider(
            "Supervisor 개수",
            min_value=1,
            max_value=5,
            value=st.session_state.supervisor_count,
            disabled=st.session_state.is_generating or not st.session_state.use_supervision, # 토글 상태에 따라 비활성화
            key="supervisor_count_slider"
        )
        st.session_state.supervision_threshold = st.slider(
            "Supervision 통과 점수 (평균)",
            min_value=0,
            max_value=100,
            value=st.session_state.supervision_threshold,
            step=5,
            disabled=st.session_state.is_generating or not st.session_state.use_supervision, # 토글 상태에 따라 비활성화
            key="supervision_threshold_slider"
        )
        if not st.session_state.use_supervision:
            st.info("Supervision 기능이 비활성화되어 있습니다. AI 답변은 바로 표시됩니다.")


# --- Main Content Area ---
# Display current conversation title and edit options
col1, col2, col3 = st.columns([0.9, 0.05, 0.05]) # Adjusted column widths
with col1:
    if not st.session_state.editing_title:
        st.subheader(f"💬 {st.session_state.current_title}")
    else:
        st.text_input("새로운 제목", key="new_title_input", value=st.session_state.new_title, label_visibility="collapsed",
                              disabled=st.session_state.is_generating or st.session_state.delete_confirmation_pending)
with col2:
    if not st.session_state.editing_title:
        if st.button("✏️", key="edit_title_button", help="대화 제목 수정",
                             disabled=st.session_state.is_generating or st.session_state.delete_confirmation_pending):
            st.session_state.editing_title = True
            st.session_state.new_title = st.session_state.current_title
            st.rerun()
    else:
        if st.button("✅", key="save_title_button", help="새로운 제목 저장",
                             disabled=st.session_state.is_generating or st.session_state.delete_confirmation_pending):
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
        if st.button("❌", key="cancel_title_button", help="제목 수정 취소",
                             disabled=st.session_state.is_generating or st.session_state.delete_confirmation_pending):
            st.session_state.editing_title = False
            st.rerun()

with col3:
    # Delete Chat Button
    is_delete_disabled = st.session_state.is_generating or \
                             (st.session_state.current_title == "새로운 대화" and not st.session_state.chat_history) or \
                             st.session_state.delete_confirmation_pending # Disable if confirmation is pending
    
    if st.button("🗑️", key="delete_chat_button", help="현재 대화 삭제", disabled=is_delete_disabled):
        # Set confirmation pending and store title to delete
        st.session_state.delete_confirmation_pending = True
        st.session_state.title_to_delete = st.session_state.current_title
        st.rerun()

# --- Delete Confirmation Pop-up (Streamlit style) ---
if st.session_state.delete_confirmation_pending:
    st.warning(f"'{st.session_state.title_to_delete}' 대화를 정말 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.", icon="⚠️")
    confirm_col1, confirm_col2 = st.columns(2)
    with confirm_col1:
        if st.button("예, 삭제합니다", key="confirm_delete_yes", use_container_width=True):
            if st.session_state.title_to_delete == "새로운 대화":
                # Clear the current "새로운 대화"
                st.session_state.chat_history = []
                st.session_state.temp_system_instruction = default_system_instruction
                st.session_state.chat_session = load_main_model(default_system_instruction).start_chat(history=[])
                st.toast("현재 대화가 초기화되었습니다.", icon="🗑️")
                # Ensure "새로운 대화" is saved as empty to Firestore
                st.session_state.saved_sessions["새로운 대화"] = []
                st.session_state.system_instructions["새로운 대화"] = default_system_instruction
                save_user_data_to_firestore(st.session_state.user_id)
            else:
                # Delete a named conversation
                deleted_title = st.session_state.title_to_delete
                if deleted_title in st.session_state.saved_sessions:
                    del st.session_state.saved_sessions[deleted_title]
                    del st.session_state.system_instructions[deleted_title]
                    
                    # After deleting, switch to "새로운 대화"
                    st.session_state.current_title = "새로운 대화"
                    st.session_state.chat_history = []
                    st.session_state.temp_system_instruction = default_system_instruction
                    st.session_state.chat_session = load_main_model(default_system_instruction).start_chat(history=[])
                    
                    st.toast(f"'{deleted_title}' 대화가 삭제되었습니다.", icon="🗑️")
                    # Ensure "새로운 대화" is saved as empty if it was the only session left
                    if "새로운 대화" not in st.session_state.saved_sessions:
                        st.session_state.saved_sessions["새로운 대화"] = []
                        st.session_state.system_instructions["새로운 대화"] = default_system_instruction
                    save_user_data_to_firestore(st.session_state.user_id)
                else:
                    st.warning(f"'{deleted_title}' 대화를 찾을 수 없습니다. 이미 삭제되었거나 저장되지 않았습니다.")
            
            st.session_state.delete_confirmation_pending = False
            st.session_state.title_to_delete = None
            st.rerun()
    with confirm_col2:
        if st.button("아니요, 취소합니다", key="confirm_delete_no", use_container_width=True):
            st.session_state.delete_confirmation_pending = False
            st.session_state.title_to_delete = None
            st.rerun()

# AI settings button and area
if st.button("⚙️ AI 설정하기", help="시스템 명령어를 설정할 수 있어요",
             disabled=st.session_state.is_generating or st.session_state.delete_confirmation_pending):
    st.session_state.editing_instruction = not st.session_state.editing_instruction

if st.session_state.editing_instruction:
    with st.expander("🧠 시스템 명령어 설정", expanded=True):
        st.session_state.temp_system_instruction = st.text_area(
            "System instruction 입력",
            value=st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction),
            height=200,
            key="system_instruction_editor",
            disabled=st.session_state.is_generating or st.session_state.delete_confirmation_pending
        )
        _, col1_ai, col2_ai = st.columns([0.9, 0.3, 0.3])
        with col1_ai:
            if st.button("✅ 저장", use_container_width=True, key="save_instruction_button",
                                 disabled=st.session_state.is_generating or st.session_state.delete_confirmation_pending):
                st.session_state.system_instructions[st.session_state.current_title] = st.session_state.temp_system_instruction
                st.session_state.saved_sessions[st.session_state.current_title] = st.session_state.chat_history.copy()
                
                # 시스템 명령어 변경 시 chat_session을 새 모델로 다시 초기화
                current_instruction = st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)
                st.session_state.chat_session = load_main_model(current_instruction).start_chat(history=convert_to_gemini_format(st.session_state.chat_history))
                
                save_user_data_to_firestore(st.session_state.user_id)
                st.success("AI 설정이 저장되었습니다.")
                st.session_state.editing_instruction = False
                st.rerun()
        with col2_ai:
            if st.button("❌ 취소", use_container_width=True, key="cancel_instruction_button",
                                 disabled=st.session_state.is_generating or st.session_state.delete_confirmation_pending):
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
            if role == "model" and i == len(st.session_state.chat_history) - 1 and not st.session_state.is_generating \
                and not st.session_state.delete_confirmation_pending: # Disable if confirmation is pending
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
    user_prompt = st.chat_input("메시지를 입력하세요.", key="user_prompt_input",
                                 disabled=st.session_state.is_generating or st.session_state.delete_confirmation_pending)

with col_upload_icon:
    # Make the image upload button look like an icon.
    uploaded_file_for_submit = st.file_uploader("🖼️", type=["png", "jpg", "jpeg"], key="file_uploader_main", label_visibility="collapsed",
                                                 disabled=st.session_state.is_generating or st.session_state.delete_confirmation_pending, help="이미지 파일을 업로드하세요.")

# Update uploaded_file state immediately upon file selection
if uploaded_file_for_submit:
    st.session_state.uploaded_file = uploaded_file_for_submit
    st.caption("이미지 업로드 완료")
else:
    # If user removes the file from the uploader, reset session state as well
    if st.session_state.uploaded_file is not None:
        st.session_state.uploaded_file = None

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

# --- Regeneration Logic ---
# This block runs only when regeneration is requested.
if st.session_state.regenerate_requested:
    st.session_state.is_generating = True # 생성 플래그를 True로 설정
    
    # 이전 사용자 메시지 (텍스트 및 이미지 데이터)를 가져옵니다.
    previous_user_message_content = st.session_state.last_user_input_for_regen["text"]
    previous_user_image_data = st.session_state.last_user_input_for_regen["image"]
    previous_user_image_mime = st.session_state.last_user_input_for_regen["mime_type"]

    regen_contents_for_model = [previous_user_message_content]
    if previous_user_image_data:
        regen_contents_for_model.append({"inline_data": {"mime_type": previous_user_image_mime, "data": previous_user_image_data}})

    with chat_display_container: # 재생성된 메시지를 채팅 영역 내에 표시
        with st.chat_message("ai"):
            message_placeholder = st.empty()
            
            best_ai_response = "" # Supervision 후 가장 좋은 답변을 저장
            highest_score = -1    # 가장 높은 점수를 저장
            
            current_instruction = st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)

            if st.session_state.use_supervision:
                attempt_count = 0
                while attempt_count < st.session_state.supervision_max_retries:
                    attempt_count += 1
                    message_placeholder.markdown(f"🤖 답변 재생성 중... (시도: {attempt_count}/{st.session_state.supervision_max_retries})")
                    full_response = ""

                    try:
                        st.session_state.chat_session = load_main_model(current_instruction).start_chat(
                            history=convert_to_gemini_format(st.session_state.chat_history) 
                        )
                        response_stream = st.session_state.chat_session.send_message(regen_contents_for_model, stream=True)
                        
                        for chunk in response_stream:
                            full_response += chunk.text
                            message_placeholder.markdown(full_response + "▌")
                        message_placeholder.markdown(full_response)

                        # --- Supervisor 평가 (재생성) ---
                        total_score = 0
                        supervisor_feedback_list = []
                        
                        for i in range(st.session_state.supervisor_count):
                            score = evaluate_response(
                                user_input=previous_user_message_content,
                                chat_history=st.session_state.chat_history, # Supervisor에게는 현재 사용자 메시지를 포함한 히스토리 제공
                                system_instruction=current_instruction,
                                ai_response=full_response
                            )
                            total_score += score
                            supervisor_feedback_list.append(f"Supervisor {i+1} 점수: {score}점")
                        
                        avg_score = total_score / st.session_state.supervisor_count
                        
                        st.info(f"재생성 평균 Supervisor 점수: {avg_score:.2f}점")
                        for feedback in supervisor_feedback_list:
                            st.info(feedback)

                        if avg_score >= st.session_state.supervision_threshold:
                            best_ai_response = full_response
                            highest_score = avg_score
                            st.success("✅ 재생성 답변이 Supervision 통과 기준을 만족합니다!")
                            break # 통과했으므로 루프 종료
                        else:
                            st.warning(f"❌ 재생성 답변이 Supervision 통과 기준({st.session_state.supervision_threshold}점)을 만족하지 못했습니다. 재시도합니다...")
                            if avg_score > highest_score: # 현재 답변이 이전 최고 점수보다 높으면 저장
                                highest_score = avg_score
                                best_ai_response = full_response
                    
                    except Exception as e:
                        st.error(f"재생성 메시지 생성 또는 평가 중 오류 발생: {e}")
                        message_placeholder.markdown("죄송합니다. 다시 생성하는 중 오류가 발생했습니다.")
                        break
            else: # Supervision is OFF for Regeneration
                message_placeholder.markdown("🤖 답변 재생성 중...")
                full_response = ""
                try:
                    st.session_state.chat_session = load_main_model(current_instruction).start_chat(
                        history=convert_to_gemini_format(st.session_state.chat_history)
                    )
                    response_stream = st.session_state.chat_session.send_message(regen_contents_for_model, stream=True)
                    
                    for chunk in response_stream:
                        full_response += chunk.text
                        message_placeholder.markdown(full_response + "▌")
                    message_placeholder.markdown(full_response)
                    best_ai_response = full_response # Directly assign the response
                    highest_score = 100 # Placeholder score, not actually used for display
                except Exception as e:
                    st.error(f"재생성 메시지 생성 중 오류 발생: {e}")
                    message_placeholder.markdown("죄송합니다. 다시 생성하는 중 오류가 발생했습니다.")

            # --- Supervision/Single-pass Logic 후 최종 재생성 AI 답변 처리 ---
            if best_ai_response:
                st.session_state.chat_history.append(("model", best_ai_response)) # 새로운 AI 메시지 추가
                message_placeholder.markdown(best_ai_response) # 최종적으로 선택된 답변을 다시 표시
                if st.session_state.use_supervision:
                    st.toast(f"재생성이 성공적으로 완료되었습니다. 최종 점수: {highest_score:.2f}점", icon="👍")
                else:
                    st.toast("재생성이 성공적으로 완료되었습니다.", icon="👍")
            else:
                st.error("모든 재시도 후에도 만족스러운 재생성 답변을 얻지 못했습니다. 이전 최고 점수 답변을 표시합니다.")
                if highest_score != -1: # 적어도 하나의 답변이 생성되었으면
                    st.session_state.chat_history.append(("model", best_ai_response))
                    message_placeholder.markdown(best_ai_response)
                    if st.session_state.use_supervision:
                        st.toast(f"최고 점수 재생성 답변이 표시되었습니다. 점수: {highest_score:.2f}점", icon="❗")
                    else:
                        st.toast("최고 점수 재생성 답변이 표시되었습니다.", icon="❗") # No score if not using supervision
                else: # 어떤 답변도 생성되지 못한 경우
                    st.session_state.chat_history.append(("model", "죄송합니다. 현재 요청에 대해 답변을 재생성할 수 없습니다."))
                    message_placeholder.markdown("죄송합니다. 현재 요청에 대해 답변을 재생성할 수 없습니다.")

            st.session_state.regenerate_requested = False # 재생성 플래그 재설정
            st.session_state.is_generating = False # 생성 플래그 재설정
            
            # 성공적인 재생성 후 Firestore에 데이터 저장
            st.session_state.saved_sessions[st.session_state.current_title] = st.session_state.chat_history.copy()
            current_instruction_for_save = st.session_state.temp_system_instruction if st.session_state.temp_system_instruction is not None else st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)
            st.session_state.system_instructions[st.session_state.current_title] = current_instruction_for_save
            save_user_data_to_firestore(st.session_state.user_id)
            st.rerun() # UI 업데이트를 위해 다시 실행


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
            
            best_ai_response = "" # Supervision 후 가장 좋은 답변을 저장
            highest_score = -1    # 가장 높은 점수를 저장
            
            current_user_prompt_text = st.session_state.chat_history[-1][1] # 마지막 추가된 사용자 메시지 텍스트
            current_user_image_data = st.session_state.last_user_input_for_regen["image"]
            current_user_image_mime = st.session_state.last_user_input_for_regen["mime_type"]

            # 모델에 보낼 초기 콘텐츠를 준비합니다.
            initial_contents_for_model = [current_user_prompt_text]
            if current_user_image_data:
                initial_contents_for_model.append({"inline_data": {"mime_type": current_user_image_mime, "data": current_user_image_data}})

            current_instruction = st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)
            history_for_main_model = st.session_state.chat_history[:-1]

            if st.session_state.use_supervision: # Supervision 토글이 켜져 있을 때만 루프 실행
                attempt_count = 0
                while attempt_count < st.session_state.supervision_max_retries:
                    attempt_count += 1
                    message_placeholder.markdown(f"🤖 답변 생성 중... (시도: {attempt_count}/{st.session_state.supervision_max_retries})")
                    full_response = "" # 현재 시도에서 모델이 생성한 답변

                    try:
                        # 새로운 답변 생성을 위해 chat_session을 이전 대화 히스토리로 다시 초기화합니다.
                        st.session_state.chat_session = load_main_model(current_instruction).start_chat(
                            history=convert_to_gemini_format(history_for_main_model)
                        )

                        # 모델에 현재 사용자 입력(및 이미지)을 전송하여 답변을 스트리밍합니다.
                        response_stream = st.session_state.chat_session.send_message(initial_contents_for_model, stream=True)
                        
                        for chunk in response_stream:
                            full_response += chunk.text
                            message_placeholder.markdown(full_response + "▌") # 스트리밍 중 커서 표시
                        message_placeholder.markdown(full_response) # 최종 답변 표시 (커서 없이)

                        # --- Supervisor 평가 시작 ---
                        total_score = 0
                        supervisor_feedback_list = []
                        
                        for i in range(st.session_state.supervisor_count):
                            score = evaluate_response(
                                user_input=current_user_prompt_text,
                                chat_history=st.session_state.chat_history[:-1], # Supervisor에게는 현재 사용자 입력 제외한 히스토리 제공
                                system_instruction=current_instruction,
                                ai_response=full_response
                            )
                            total_score += score
                            supervisor_feedback_list.append(f"Supervisor {i+1} 점수: {score}점")
                        
                        avg_score = total_score / st.session_state.supervisor_count
                        
                        st.info(f"평균 Supervisor 점수: {avg_score:.2f}점")
                        for feedback in supervisor_feedback_list:
                            st.info(feedback)

                        if avg_score >= st.session_state.supervision_threshold:
                            best_ai_response = full_response
                            highest_score = avg_score
                            st.success("✅ 답변이 Supervision 통과 기준을 만족합니다!")
                            break # 통과했으므로 루프 종료
                        else:
                            st.warning(f"❌ 답변이 Supervision 통과 기준({st.session_state.supervision_threshold}점)을 만족하지 못했습니다. 재시도합니다...")
                            if avg_score > highest_score: # 현재 답변이 이전 최고 점수보다 높으면 저장
                                highest_score = avg_score
                                best_ai_response = full_response

                    except Exception as e:
                        st.error(f"메시지 생성 또는 평가 중 오류 발생: {e}")
                        message_placeholder.markdown("죄송합니다. 메시지를 처리하는 중 오류가 발생했습니다.")
                        st.session_state.uploaded_file = None # 오류 발생 시 업로드된 파일 초기화
                        break # 오류 발생 시 루프 종료
            else: # Supervision is OFF (Supervision 토글이 꺼져 있을 때)
                message_placeholder.markdown("🤖 답변 생성 중...")
                full_response = ""
                try:
                    st.session_state.chat_session = load_main_model(current_instruction).start_chat(
                        history=convert_to_gemini_format(history_for_main_model)
                    )
                    response_stream = st.session_state.chat_session.send_message(initial_contents_for_model, stream=True)
                    
                    for chunk in response_stream:
                        full_response += chunk.text
                        message_placeholder.markdown(full_response + "▌")
                    message_placeholder.markdown(full_response)
                    best_ai_response = full_response # Supervision이 꺼져 있으면 바로 이 답변을 채택
                    highest_score = 100 # Supervision이 아니므로 점수는 의미 없지만 토스트 메시지 일관성을 위해 임의 값 부여
                except Exception as e:
                    st.error(f"메시지 생성 중 오류 발생: {e}")
                    message_placeholder.markdown("죄송합니다. 메시지를 처리하는 중 오류가 발생했습니다.")
                    st.session_state.uploaded_file = None

            # --- Supervision/Single-pass Logic 후 최종 AI 답변 처리 ---
            if best_ai_response:
                st.session_state.chat_history.append(("model", best_ai_response))
                message_placeholder.markdown(best_ai_response)
                if st.session_state.use_supervision: # Supervision 활성화 여부에 따라 토스트 메시지 변경
                    st.toast(f"대화가 성공적으로 완료되었습니다. 최종 점수: {highest_score:.2f}점", icon="👍")
                else:
                    st.toast("대화가 성공적으로 완료되었습니다.", icon="👍") # Supervision 비활성화 시 점수 표시 안 함
            else:
                st.error("모든 재시도 후에도 만족스러운 답변을 얻지 못했습니다. 이전 최고 점수 답변을 표시합니다.")
                if highest_score != -1: # 적어도 하나의 답변이 생성되었으면 (최고 점수 답변이 있으면)
                    st.session_state.chat_history.append(("model", best_ai_response))
                    message_placeholder.markdown(best_ai_response)
                    if st.session_state.use_supervision: # Supervision 활성화 여부에 따라 토스트 메시지 변경
                        st.toast(f"최고 점수 답변이 표시되었습니다. 점수: {highest_score:.2f}점", icon="❗")
                    else:
                        st.toast("최고 점수 답변이 표시되었습니다.", icon="❗") # Supervision 비활성화 시 점수 표시 안 함
                else: # 어떤 답변도 생성되지 못한 경우
                    st.session_state.chat_history.append(("model", "죄송합니다. 현재 요청에 대해 답변을 생성할 수 없습니다."))
                    message_placeholder.markdown("죄송합니다. 현재 요청에 대해 답변을 생성할 수 없습니다.")

            st.session_state.uploaded_file = None
            st.session_state.is_generating = False

            # 첫 상호작용 시 대화 제목 자동 생성 (Supervision 루프 완료 후)
            if st.session_state.current_title == "새로운 대화" and \
               len(st.session_state.chat_history) >= 2 and \
               st.session_state.chat_history[-2][0] == "user" and st.session_state.chat_history[-1][0] == "model":
                with st.spinner("대화 제목 생성 중..."):
                    try:
                        summary_prompt_text = st.session_state.chat_history[-2][1] # 사용자 프롬프트 가져오기
                        summary = summary_model.generate_content(f"다음 사용자의 메시지를 요약해서 대화 제목으로 만들어줘 (한 문장, 30자 이내):\n\n{summary_prompt_text}")
                        original_title = summary.text.strip().replace("\n", " ").replace('"', '')
                        if not original_title or len(original_title) > 30: # 30자 이상이면 기본 제목 사용
                            original_title = "새로운 대화"
                    except Exception as e:
                        print(f"제목 생성 오류: {e}. 기본 제목 사용.")
                        original_title = "새로운 대화"

                    title_key = original_title
                    count = 1
                    while title_key in st.session_state.saved_sessions:
                        title_key = f"{original_title} ({count})"
                        count += 1
                    st.session_state.current_title = title_key
                    st.toast(f"대화 제목이 '{title_key}'로 설정되었습니다.", icon="📝")

            # 성공적인 생성 후 Firestore에 데이터 저장 (Supervision 루프 완료 후)
            st.session_state.saved_sessions[st.session_state.current_title] = st.session_state.chat_history.copy()
            current_instruction_for_save = st.session_state.temp_system_instruction if st.session_state.temp_system_instruction is not None else st.session_state.system_instructions.get(st.session_state.current_title, default_system_instruction)
            st.session_state.system_instructions[st.session_state.current_title] = current_instruction_for_save
            save_user_data_to_firestore(st.session_state.user_id)
            
            st.rerun() # UI 업데이트를 위해 다시 실행

