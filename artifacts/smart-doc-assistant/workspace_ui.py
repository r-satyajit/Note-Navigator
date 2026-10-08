from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_google_genai import ChatGoogleGenerativeAI

import database
from auth import (
    is_valid_email,
    normalize_email,
    perform_dummy_password_check,
    hash_password,
    validate_password,
    verify_password,
)
from ingestion import (
    build_vector_store,
    load_documents_from_bytes,
    restore_vector_store,
    serialize_vector_store,
    source_label,
)
from quiz import DIFFICULTY_LEVELS, generate_quiz
from storage_bridge import StorageBridge, StorageBridgeError
from theme import apply_aurora_theme


load_dotenv()

CHAT_MODEL = "gemini-3.8-flash"
RETRIEVAL_COUNT = 4
SUPPORTED_EXTENSIONS = {"pdf", "txt", "ppt", "pptx"}


def get_gemini_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _init_session_state() -> None:
    defaults: dict[str, Any] = {
        "auth_user_id": None,
        "space_selectbox": None,
        "chat_selectbox": None,
        "cached_vector_store": None,
        "cached_index_path": None,
        "cached_index_user_id": None,
        "cached_index_space_id": None,
        "active_quiz": None,
        "quiz_result": None,
        "pending_question": None,
        "flash_message": None,
        "pending_space_delete_id": None,
        "pending_document_delete": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _sign_in(user: dict[str, Any]) -> None:
    st.session_state.auth_user_id = user["id"]
    st.session_state.space_selectbox = None
    st.session_state.chat_selectbox = None
    st.session_state.cached_vector_store = None
    st.session_state.cached_index_path = None
    st.session_state.cached_index_user_id = None
    st.session_state.cached_index_space_id = None
    st.session_state.active_quiz = None
    st.session_state.quiz_result = None
    st.session_state.pending_question = None


def _sign_out() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def render_auth_screen() -> None:
    left, center, right = st.columns([1, 1.15, 1])
    with center:
        st.markdown(
            '<div class="nn-kicker">Private study workspace</div>',
            unsafe_allow_html=True,
        )
        st.markdown("# Notes Navigator")
        st.write(
            "Keep your study spaces, documents, and conversations together in a private account."
        )

        login_tab, signup_tab = st.tabs(["Sign in", "Create account"])
        with login_tab:
            with st.form("login_form"):
                email_input = st.text_input(
                    "Email address",
                    autocomplete="email",
                    key="login_email",
                )
                password_input = st.text_input(
                    "Password",
                    type="password",
                    autocomplete="current-password",
                    key="login_password",
                )
                login_submitted = st.form_submit_button(
                    "Sign in",
                    use_container_width=True,
                )

            if login_submitted:
                email = normalize_email(email_input)
                if not is_valid_email(email):
                    st.error("Enter a valid email address.")
                elif database.is_login_rate_limited(email):
                    st.error(
                        "Sign-in is temporarily unavailable after several unsuccessful attempts. Try again in 15 minutes."
                    )
                else:
                    user = database.get_user_by_email(email)
                    if user is None:
                        perform_dummy_password_check(password_input)
                        valid_password = False
                    else:
                        valid_password = verify_password(
                            password_input,
                            user["password_salt"],
                            user["password_hash"],
                        )

                    if user is not None and valid_password:
                        database.clear_login_failures(email)
                        database.touch_user_login(user["id"])
                        _sign_in(user)
                        st.rerun()
                    else:
                        database.record_login_failure(email)
                        st.error("Email or password wasn't recognized.")

        with signup_tab:
            with st.form("signup_form"):
                signup_email_input = st.text_input(
                    "Email address",
                    autocomplete="email",
                    key="signup_email",
                )
                signup_password_input = st.text_input(
                    "Password",
                    type="password",
                    autocomplete="new-password",
                    help="Use at least 12 characters.",
                    key="signup_password",
                )
                confirmation_input = st.text_input(
                    "Confirm password",
                    type="password",
                    autocomplete="new-password",
                    key="signup_password_confirmation",
                )
                signup_submitted = st.form_submit_button(
                    "Create account",
                    use_container_width=True,
                )

            if signup_submitted:
                email = normalize_email(signup_email_input)
                password_error = validate_password(signup_password_input)
                if not is_valid_email(email):
                    st.error("Enter a valid email address.")
                elif password_error:
                    st.error(password_error)
                elif signup_password_input != confirmation_input:
                    st.error("The passwords don't match.")
                else:
                    salt, password_hash = hash_password(signup_password_input)
                    try:
                        account = database.create_account(
                            email,
                            salt,
                            password_hash,
                        )
                    except sqlite3.IntegrityError:
                        st.error("An account with that email already exists.")
                    else:
                        _sign_in(account)
                        st.rerun()

        st.caption(
            "Your password is stored as a salted scrypt hash. Notes Navigator does not use Replit or third-party sign-in."
        )


def _set_flash(kind: str, message: str) -> None:
    st.session_state.flash_message = (kind, message)


def _clear_vector_cache() -> None:
    st.session_state.cached_vector_store = None
    st.session_state.cached_index_path = None
    st.session_state.cached_index_user_id = None
    st.session_state.cached_index_space_id = None


def _process_pending_deletions(user_id: str) -> None:
    pending_space_id = st.session_state.pop("pending_space_delete_id", None)
    if pending_space_id:
        try:
            if database.get_space(user_id, pending_space_id) is None:
                raise ValueError("That Space no longer exists.")
            bridge = StorageBridge()
            for object_path in database.get_space_object_paths(user_id, pending_space_id):
                bridge.delete(user_id=user_id, object_path=object_path)
            if not database.delete_space(user_id, pending_space_id):
                raise ValueError("That Space could not be deleted.")
            spaces = database.list_spaces(user_id)
            st.session_state.space_selectbox = spaces[0]["id"] if spaces else None
            st.session_state.pop("chat_selectbox", None)
            st.session_state.active_quiz = None
            st.session_state.quiz_result = None
            _clear_vector_cache()
            _set_flash("success", "The Space and its stored files were deleted.")
        except Exception as error:
            _set_flash("error", f"Space deletion failed: {error}")

    pending_document = st.session_state.pop("pending_document_delete", None)
    if not pending_document:
        return
    target_space_id = pending_document.get("space_id")
    document_id = pending_document.get("document_id")
    if not isinstance(target_space_id, str) or not isinstance(document_id, str):
        return

    try:
        document = next(
            (
                item
                for item in database.list_documents(user_id, target_space_id)
                if item["id"] == document_id
            ),
            None,
        )
        if document is None:
            raise ValueError("That document no longer exists.")

        bridge = StorageBridge()
        old_index = database.get_space_index(user_id, target_space_id)
        if old_index is not None:
            database.delete_space_index(user_id, target_space_id)
            try:
                bridge.delete(user_id=user_id, object_path=old_index["object_path"])
            except StorageBridgeError:
                # The database reference is removed so a stale index cannot answer.
                pass

        bridge.delete(user_id=user_id, object_path=document["object_path"])
        if database.delete_document(user_id, target_space_id, document_id) is None:
            raise ValueError("That document could not be removed from the Space.")
        _clear_vector_cache()
        st.session_state.active_quiz = None
        st.session_state.quiz_result = None
        remaining_documents = database.list_documents(user_id, target_space_id)
        if remaining_documents and get_gemini_api_key():
            _rebuild_space_index(user_id, target_space_id, bridge)
            _set_flash("success", "Document deleted and the Space index rebuilt.")
        else:
            _set_flash("success", "Document deleted. Rebuild the index after adding documents.")
    except Exception as error:
        _set_flash("error", f"Document deletion failed: {error}")


def _consume_flash_message() -> None:
    flash = st.session_state.pop("flash_message", None)
    if not flash:
        return
    kind, message = flash
    if kind == "success":
        st.success(message)
    elif kind == "warning":
        st.warning(message)
    else:
        st.error(message)


def _title_from_question(question: str) -> str:
    title = " ".join(question.split()).strip()
    return title[:56] + ("…" if len(title) > 56 else "")


def _messages_from_chat(chat: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        payload = json.loads(chat["history_json"])
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    messages: list[dict[str, Any]] = []
    for message in payload:
        if (
            isinstance(message, dict)
            and message.get("role") in {"user", "assistant"}
            and isinstance(message.get("content"), str)
        ):
            cleaned: dict[str, Any] = {
                "role": message["role"],
                "content": message["content"],
            }
            if message["role"] == "assistant" and isinstance(message.get("sources"), list):
                cleaned["sources"] = [
                    source
                    for source in message["sources"]
                    if isinstance(source, dict)
                    and isinstance(source.get("label"), str)
                    and isinstance(source.get("content"), str)
                ]
            messages.append(cleaned)
    return messages


def _recent_conversation(messages: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"{'User' if message['role'] == 'user' else 'Assistant'}: {message['content']}"
        for message in messages[-6:]
    )


def _make_answer(
    question: str,
    history: str,
    documents: list[Document],
    api_key: str,
) -> str:
    context = "\n\n---\n\n".join(
        f"[SOURCE {index}: {source_label(document.metadata)}]\n{document.page_content}"
        for index, document in enumerate(documents, start=1)
    )
    prompt = f"""You are a careful assistant answering questions about the user's documents.
Use only the supplied source passages for factual claims. If they do not contain the
answer, say that the uploaded documents do not provide enough information. Do not
invent details. When useful, refer to a source by its filename and page or slide.

Recent conversation:
{history or "(No earlier messages.)"}

Current question:
{question}

Retrieved document passages:
{context}

Answer clearly and directly. Treat the current question as a follow-up when the
conversation makes that intent clear."""
    model = ChatGoogleGenerativeAI(
        model=CHAT_MODEL,
        temperature=0.2,
        api_key=api_key,
    )
    response = model.invoke(prompt)
    content = response.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts = [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("text")
        ]
        if text_parts:
            return "\n".join(text_parts).strip()
    return str(content).strip()


def _load_space_vector_store(
    user_id: str,
    space_id: str,
    bridge: StorageBridge,
    api_key: str,
) -> FAISS | None:
    index_record = database.get_space_index(user_id, space_id)
    if index_record is None:
        return None
    object_path = index_record["object_path"]
    if (
        st.session_state.cached_vector_store is not None
        and st.session_state.cached_index_path == object_path
        and st.session_state.cached_index_user_id == user_id
        and st.session_state.cached_index_space_id == space_id
    ):
        return st.session_state.cached_vector_store

    serialized = bridge.download(user_id=user_id, object_path=object_path)
    vector_store = restore_vector_store(serialized, api_key=api_key)
    st.session_state.cached_vector_store = vector_store
    st.session_state.cached_index_path = object_path
    st.session_state.cached_index_user_id = user_id
    st.session_state.cached_index_space_id = space_id
    return vector_store


def _rebuild_space_index(
    user_id: str,
    space_id: str,
    bridge: StorageBridge,
    parsed_documents: dict[str, list[Document]] | None = None,
) -> tuple[FAISS, int]:
    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError("Gemini is not configured. Add GEMINI_API_KEY to continue.")
    document_rows = database.list_documents(user_id, space_id)
    if not document_rows:
        raise ValueError("Add a document before building the Space index.")

    documents: list[Document] = []
    parsed_documents = parsed_documents or {}
    for document in document_rows:
        cached = parsed_documents.get(document["id"])
        if cached is not None:
            documents.extend(cached)
            continue
        content = bridge.download(
            user_id=user_id,
            object_path=document["object_path"],
        )
        loaded = load_documents_from_bytes(document["file_name"], content)
        documents.extend(loaded)

    vector_store, chunk_count = build_vector_store(documents, api_key=api_key)
    serialized_index = serialize_vector_store(vector_store)
    new_index_path = bridge.upload(
        user_id=user_id,
        space_id=space_id,
        content=serialized_index,
        content_type="application/octet-stream",
    )
    previous_index = database.get_space_index(user_id, space_id)
    database.set_space_index(
        user_id,
        space_id,
        new_index_path,
        chunk_count,
    )
    _clear_vector_cache()
    st.session_state.cached_vector_store = vector_store
    st.session_state.cached_index_path = new_index_path
    st.session_state.cached_index_user_id = user_id
    st.session_state.cached_index_space_id = space_id
    if previous_index and previous_index["object_path"] != new_index_path:
        try:
            bridge.delete(
                user_id=user_id,
                object_path=previous_index["object_path"],
            )
        except StorageBridgeError:
            pass
    return vector_store, chunk_count


def _process_uploads(
    user_id: str,
    space_id: str,
    uploaded_files: list[Any],
    bridge: StorageBridge,
) -> tuple[int, int, list[str]]:
    existing_hashes = {
        document["sha256"]
        for document in database.list_documents(user_id, space_id)
    }
    parsed_new_documents: dict[str, list[Document]] = {}
    added_count = 0
    skipped_count = 0
    errors: list[str] = []

    for uploaded_file in uploaded_files:
        file_name = Path(uploaded_file.name).name
        content = uploaded_file.getvalue()
        digest = hashlib.sha256(content).hexdigest()
        if digest in existing_hashes:
            skipped_count += 1
            continue
        try:
            if len(content) > 100 * 1024 * 1024:
                raise ValueError("The maximum file size is 100 MB.")
            suffix = Path(file_name).suffix.lower().lstrip(".")
            if suffix not in SUPPORTED_EXTENSIONS:
                raise ValueError("Only PDF, TXT, PPT, and PPTX files are supported.")
            loaded_documents = load_documents_from_bytes(file_name, content)
            if not any(document.page_content.strip() for document in loaded_documents):
                raise ValueError("No readable text was found in this file.")

            object_path = bridge.upload(
                user_id=user_id,
                space_id=space_id,
                content=content,
                content_type=mimetypes.guess_type(file_name)[0]
                or "application/octet-stream",
            )
            document_id = str(uuid.uuid4())
            try:
                database.add_document(
                    document_id=document_id,
                    user_id=user_id,
                    space_id=space_id,
                    file_name=file_name,
                    object_path=object_path,
                    sha256=digest,
                    byte_size=len(content),
                )
            except Exception:
                try:
                    bridge.delete(user_id=user_id, object_path=object_path)
                except StorageBridgeError:
                    pass
                raise

            parsed_new_documents[document_id] = loaded_documents
            existing_hashes.add(digest)
            added_count += 1
        except Exception as error:
            errors.append(f"{file_name}: {error}")

    if added_count:
        try:
            _rebuild_space_index(
                user_id,
                space_id,
                bridge,
                parsed_documents=parsed_new_documents,
            )
        except Exception as error:
            errors.append(f"Files were stored, but the Space index could not be built: {error}")
    return added_count, skipped_count, errors


def _render_sources(sources: list[dict[str, str]]) -> None:
    if not sources:
        return
    with st.expander(f"Referenced passages · {len(sources)}"):
        st.caption("These are the passages returned by document search.")
        for index, source in enumerate(sources, start=1):
            with st.container(border=True):
                st.markdown(f"**Passage {index:02d} · {source['label']}**")
                st.text(source["content"])


def _render_chat(
    user_id: str,
    space_id: str,
    chat: dict[str, Any],
    vector_store: FAISS | None,
    bridge: StorageBridge,
    api_key: str | None,
) -> None:
    messages = _messages_from_chat(chat)
    for message in messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                _render_sources(message.get("sources", []))

    is_ready = vector_store is not None and bool(api_key)
    if is_ready:
        with st.container(key="quick_prompts"):
            st.markdown('<div class="nn-section-label">Start with a question</div>', unsafe_allow_html=True)
            quick_prompts = [
                ("Summarize themes", "Summarize the key themes across my documents."),
                ("Key terms", "List the core terms and definitions I should know."),
                ("Explain the argument", "What is the central argument, and what evidence supports it?"),
                ("Compare concepts", "Compare the key concepts covered in my documents."),
            ]
            prompt_columns = st.columns(4)
            for prompt_index, (prompt_label, prompt_text) in enumerate(quick_prompts):
                with prompt_columns[prompt_index]:
                    if st.button(
                        prompt_label,
                        key=f"quick_prompt_{space_id}_{chat['id']}_{prompt_index}",
                        use_container_width=True,
                    ):
                        st.session_state.pending_question = prompt_text

    question = st.chat_input(
        "Ask a question about this Space's documents…",
        disabled=not is_ready,
        key=f"question_input_{space_id}_{chat['id']}",
    )
    if st.session_state.pending_question:
        question = st.session_state.pop("pending_question")
    if not question or not question.strip():
        return
    question = question.strip()
    if len(question) > 4000:
        st.error("Keep questions under 4,000 characters.")
        return
    if vector_store is None or api_key is None:
        st.warning("Build the Space index and configure Gemini before asking questions.")
        return

    history = _recent_conversation(messages)
    messages.append({"role": "user", "content": question})
    title = chat["title"]
    if not any(message["role"] == "user" for message in _messages_from_chat(chat)):
        title = _title_from_question(question)
    database.save_chat(user_id, space_id, chat["id"], title, messages)

    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Searching this Space and preparing an answer…"):
            try:
                query = f"Recent conversation:\n{history}\n\nCurrent question: {question}"
                retrieved_documents = vector_store.similarity_search(
                    query,
                    k=RETRIEVAL_COUNT,
                )
                if not retrieved_documents:
                    answer = (
                        "I couldn't find a matching passage in this Space. Try rephrasing the question."
                    )
                    sources: list[dict[str, str]] = []
                else:
                    answer = _make_answer(
                        question,
                        history,
                        retrieved_documents,
                        api_key,
                    )
                    sources = [
                        {
                            "label": source_label(document.metadata),
                            "content": document.page_content,
                        }
                        for document in retrieved_documents
                    ]
            except Exception as error:
                st.error(f"Gemini could not complete this request: {error}")
                answer = (
                    "I couldn't complete that request. Check that Gemini is available, then try again."
                )
                sources = []
        st.markdown(answer)
        _render_sources(sources)
    messages.append(
        {"role": "assistant", "content": answer, "sources": sources}
    )
    database.save_chat(user_id, space_id, chat["id"], title, messages)


def _render_documents(
    user_id: str,
    space_id: str,
    bridge: StorageBridge,
    api_key: str | None,
) -> None:
    documents = database.list_documents(user_id, space_id)
    index_record = database.get_space_index(user_id, space_id)
    stat_columns = st.columns(2)
    with stat_columns[0]:
        st.metric("Documents", len(documents))
    with stat_columns[1]:
        st.metric(
            "Searchable passages",
            index_record["chunk_count"] if index_record else 0,
        )
    st.caption("Files and indexes are private to your account and this Space.")

    with st.form("upload_documents_form", clear_on_submit=True):
        uploaded_files = st.file_uploader(
            "Add documents",
            type=sorted(SUPPORTED_EXTENSIONS),
            accept_multiple_files=True,
            max_upload_size=100,
            help="PDF, TXT, PPT, and PPTX files are supported. Each file may be up to 100 MB.",
            disabled=not bool(api_key),
            key=f"upload_documents_{space_id}",
        )
        submitted = st.form_submit_button(
            "Upload and index",
            use_container_width=True,
            disabled=not bool(api_key),
        )
    if not api_key:
        st.warning("Set GEMINI_API_KEY or GOOGLE_API_KEY before uploading and indexing documents.")
    if submitted:
        if not uploaded_files:
            st.info("Choose at least one file.")
        else:
            try:
                with st.spinner("Saving documents and building this Space's index…"):
                    added_count, skipped_count, errors = _process_uploads(
                        user_id,
                        space_id,
                        uploaded_files,
                        bridge,
                    )
                if added_count:
                    st.success(f"Added {added_count} document(s).")
                if skipped_count:
                    st.info(f"Skipped {skipped_count} duplicate document(s).")
                for error in errors:
                    st.error(error)
            except StorageBridgeError as error:
                st.error(f"Private storage could not save the upload: {error}")
            except Exception as error:
                st.error(f"Upload failed: {error}")

    documents = database.list_documents(user_id, space_id)
    index_record = database.get_space_index(user_id, space_id)
    if documents:
        st.markdown('<div class="nn-section-label">Documents in this Space</div>', unsafe_allow_html=True)
        for document in documents:
            with st.expander(
                f"{document['file_name']} · {document['byte_size'] / 1024:.0f} KB"
            ):
                st.caption(f"Added {document['created_at']}")
                st.caption(f"SHA-256: {document['sha256'][:16]}…")
                confirm = st.checkbox(
                    "Confirm permanent deletion",
                    key=f"confirm_delete_{document['id']}",
                )
                if st.button(
                    "Delete document",
                    key=f"delete_document_{document['id']}",
                    disabled=not confirm,
                ):
                    st.session_state.pending_document_delete = {
                        "space_id": space_id,
                        "document_id": document["id"],
                    }
                    st.rerun()

        if api_key:
            if st.button(
                "Rebuild Space index",
                key=f"rebuild_index_{space_id}",
                use_container_width=True,
            ):
                try:
                    with st.spinner("Rebuilding the Space index…"):
                        _rebuild_space_index(user_id, space_id, bridge)
                    st.success("The Space index is up to date.")
                except Exception as error:
                    st.error(f"Index rebuild failed: {error}")
        elif documents and index_record is None:
            st.info("Configure Gemini to build the searchable index.")
    else:
        st.info("This Space does not contain documents yet. Upload a file to build its private index.")


def _render_quiz(
    user_id: str,
    space_id: str,
    vector_store: FAISS | None,
    api_key: str | None,
) -> None:
    if vector_store is None:
        st.info("Add and index documents in this Space before creating a practice quiz.")
        return
    if not api_key:
        st.warning("Gemini is not configured.")
        return

    difficulty = st.selectbox(
        "Difficulty",
        options=DIFFICULTY_LEVELS,
        key=f"quiz_difficulty_{space_id}",
    )
    if st.button(
        "Generate five questions",
        key=f"generate_quiz_{space_id}",
        type="primary",
    ):
        try:
            with st.spinner("Creating five questions from this Space's documents…"):
                quiz_data = generate_quiz(
                    vector_store,
                    difficulty=difficulty,
                    api_key=api_key,
                )
            quiz_data["id"] = str(uuid.uuid4())
            quiz_data["space_id"] = space_id
            st.session_state.active_quiz = quiz_data
            st.session_state.quiz_result = None
        except Exception as error:
            st.error(f"Could not generate the quiz: {error}")

    quiz_data = st.session_state.active_quiz
    if not isinstance(quiz_data, dict) or quiz_data.get("space_id") != space_id:
        return
    quiz_id = quiz_data["id"]
    st.markdown(f"### {quiz_data['difficulty']} practice quiz")
    with st.form(f"quiz_answers_{quiz_id}"):
        answer_keys: list[str] = []
        for question_index, question in enumerate(quiz_data["questions"]):
            st.markdown(f"**{question_index + 1}. {question['question']}**")
            answer_key = f"quiz_answer_{quiz_id}_{question_index}"
            answer_keys.append(answer_key)
            st.radio(
                f"Choose an answer for question {question_index + 1}",
                options=question["options"],
                index=None,
                key=answer_key,
                label_visibility="collapsed",
            )
        submitted = st.form_submit_button("Score quiz", use_container_width=True)

    if submitted:
        answered = [
            st.session_state.get(answer_key)
            for answer_key in answer_keys
        ]
        if any(answer is None for answer in answered):
            st.warning("Answer all five questions before scoring the quiz.")
        else:
            score = sum(
                answer == question["options"][question["answer_index"]]
                for answer, question in zip(answered, quiz_data["questions"])
            )
            st.session_state.quiz_result = {
                "quiz_id": quiz_id,
                "score": score,
            }

    result = st.session_state.quiz_result
    if isinstance(result, dict) and result.get("quiz_id") == quiz_id:
        st.metric("Your score", f"{result['score']} / 5")
        with st.expander("Review answers and explanations"):
            for index, question in enumerate(quiz_data["questions"], start=1):
                correct = question["options"][question["answer_index"]]
                st.markdown(f"**{index}. {question['question']}**")
                st.write(f"Correct answer: {correct}")
                st.caption(question["explanation"])
        export = {
            "difficulty": quiz_data["difficulty"],
            "questions": quiz_data["questions"],
        }
        st.download_button(
            "Download quiz as JSON",
            data=json.dumps(export, ensure_ascii=False, indent=2),
            file_name="notes-navigator-quiz.json",
            mime="application/json",
        )


def _render_space_settings(
    user_id: str,
    space: dict[str, Any],
    space_count: int,
) -> None:
    with st.expander("Space settings"):
        with st.form(f"rename_space_form_{space['id']}"):
            new_name = st.text_input(
                "Space name",
                value=space["name"],
                max_chars=80,
                key=f"rename_space_name_{space['id']}",
            )
            rename_submitted = st.form_submit_button("Save name")
        if rename_submitted:
            if not new_name.strip():
                st.error("Give this Space a name.")
            elif database.rename_space(user_id, space["id"], new_name):
                st.session_state.flash_message = ("success", "Space name updated.")
                st.rerun()

        if space_count > 1:
            st.divider()
            st.caption("Deleting a Space permanently removes its chats, documents, and index.")
            confirmed = st.checkbox(
                "I understand this cannot be undone",
                key=f"confirm_delete_space_{space['id']}",
            )
            if st.button(
                "Delete this Space",
                key=f"delete_space_{space['id']}",
                disabled=not confirmed,
            ):
                st.session_state.pending_space_delete_id = space["id"]
                st.rerun()


def render_workspace(user: dict[str, Any]) -> None:
    user_id = user["id"]
    _process_pending_deletions(user_id)
    _consume_flash_message()

    with st.sidebar:
        st.markdown('<div class="nn-kicker">Notes Navigator</div>', unsafe_allow_html=True)
        st.caption(f"Signed in as {user['email']}")
        if st.button("Sign out", use_container_width=True):
            _sign_out()
            st.rerun()
        st.divider()

        with st.form("create_space_form"):
            new_space_name = st.text_input(
                "Create a Space",
                placeholder="e.g. Biology 101",
                max_chars=80,
            )
            create_space_submitted = st.form_submit_button(
                "Create Space",
                use_container_width=True,
            )
        if create_space_submitted:
            if not new_space_name.strip():
                st.error("Give the Space a name.")
            else:
                try:
                    new_space_id = database.create_space(user_id, new_space_name)
                    new_chat_id = database.create_chat(user_id, new_space_id)
                    st.session_state.space_selectbox = new_space_id
                    st.session_state.chat_selectbox = new_chat_id
                    st.session_state.active_quiz = None
                    st.session_state.quiz_result = None
                    _clear_vector_cache()
                    st.rerun()
                except Exception as error:
                    st.error(f"Could not create the Space: {error}")

        spaces = database.list_spaces(user_id)
        if spaces:
            space_names = {space["id"]: space["name"] for space in spaces}
            available_space_ids = list(space_names)
            if st.session_state.space_selectbox not in available_space_ids:
                st.session_state.space_selectbox = available_space_ids[0]
            space_id = st.selectbox(
                "Current Space",
                options=available_space_ids,
                format_func=lambda value: space_names.get(value, "Space"),
                key="space_selectbox",
            )
            selected_space = next(space for space in spaces if space["id"] == space_id)

            chats = database.list_chats(user_id, space_id)
            if not chats:
                new_chat_id = database.create_chat(user_id, space_id)
                st.session_state.chat_selectbox = new_chat_id
                st.rerun()
            chat_map = {chat["id"]: chat for chat in chats}
            if st.session_state.chat_selectbox not in chat_map:
                st.session_state.chat_selectbox = chats[0]["id"]
            with st.form(f"create_chat_form_{space_id}"):
                create_chat_submitted = st.form_submit_button(
                    "＋ New conversation",
                    use_container_width=True,
                )
            if create_chat_submitted:
                new_chat_id = database.create_chat(user_id, space_id)
                st.session_state.chat_selectbox = new_chat_id
                st.rerun()
            chat_id = st.selectbox(
                "Conversations",
                options=list(chat_map),
                format_func=lambda value: chat_map[value]["title"],
                key="chat_selectbox",
            )
            selected_chat = database.get_chat(user_id, space_id, chat_id)
            if selected_chat is None:
                st.warning("That conversation is unavailable.")
                return
            if st.button(
                "Clear current conversation",
                key=f"clear_chat_{chat_id}",
                use_container_width=True,
            ):
                database.save_chat(user_id, space_id, chat_id, "New conversation", [])
                st.session_state.flash_message = ("success", "Conversation cleared.")
                st.rerun()
            _render_space_settings(user_id, selected_space, len(spaces))

            documents = database.list_documents(user_id, space_id)
            index_record = database.get_space_index(user_id, space_id)
            st.divider()
            st.markdown('<div class="nn-section-label">This Space</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="nn-library-stat"><span class="nn-library-stat-number">{len(documents)}</span><span class="nn-library-stat-label">documents</span></div>',
                unsafe_allow_html=True,
            )
            st.caption(
                f"{index_record['chunk_count'] if index_record else 0} searchable passages"
            )
        else:
            space_id = None
            selected_space = None
            selected_chat = None

    st.markdown('<div class="nn-kicker">Grounded study workspace</div>', unsafe_allow_html=True)
    if selected_space is None or selected_chat is None or space_id is None:
        st.markdown("# Notes Navigator")
        st.write("Create a Space in the sidebar to keep its documents and conversations together.")
        return

    st.title(selected_space["name"])
    st.caption(
        "Ask source-grounded questions, organize multiple conversations, or generate a five-question practice quiz."
    )
    view = st.segmented_control(
        "Workspace",
        options=["Chat", "Documents", "Practice quiz"],
        default="Chat",
        label_visibility="collapsed",
        key=f"workspace_view_{space_id}",
    )
    if view is None:
        view = "Chat"

    api_key = get_gemini_api_key()
    try:
        bridge = StorageBridge()
    except StorageBridgeError as error:
        st.error(str(error))
        return

    if view == "Documents":
        _render_documents(user_id, space_id, bridge, api_key)
        return

    vector_store: FAISS | None = None
    index_record = database.get_space_index(user_id, space_id)
    if api_key and index_record:
        try:
            with st.spinner("Loading this Space's private index…"):
                vector_store = _load_space_vector_store(
                    user_id,
                    space_id,
                    bridge,
                    api_key,
                )
        except Exception as error:
            st.error(f"The Space index could not be loaded: {error}")
            st.info("Open Documents and rebuild the index to continue.")
    elif not api_key:
        st.warning("Add GEMINI_API_KEY or GOOGLE_API_KEY to enable Gemini features.")
    elif not index_record:
        st.info("Add and index documents in this Space to enable chat and quizzes.")

    if view == "Practice quiz":
        _render_quiz(user_id, space_id, vector_store, api_key)
        return

    _render_chat(
        user_id,
        space_id,
        selected_chat,
        vector_store,
        bridge,
        api_key,
    )


def main() -> None:
    st.set_page_config(
        page_title="Notes Navigator",
        page_icon="✦",
        layout="wide",
    )
    _init_session_state()
    database.initialize_database()
    apply_aurora_theme()

    user_id = st.session_state.get("auth_user_id")
    user = database.get_user_by_id(user_id) if isinstance(user_id, str) else None
    if user is None:
        if user_id:
            _sign_out()
        render_auth_screen()
        return
    render_workspace(user)


if __name__ == "__main__":
    main()
