import grpc
import sys  # Import sys for flushing output
import json
import re
import os
from typing import Optional, Literal, Dict, Any
from pydantic import BaseModel, Field
from langchain_ollama import OllamaLLM
import filesearch_pb2
import filesearch_pb2_grpc

# --- 0. System policy for tool routing ---
SYSTEM_POLICY = (
    "You are an assistant for MCP-File-Manager. Follow this tool-use policy strictly.\n"
    "When to call the tool:\n"
    "- Call remote_file_search when the user asks to find files or folders by name, glob/pattern, size, or modified time within allowed locations.\n"
    "When NOT to call the tool:\n"
    "- Do not call tools for purely conceptual questions (e.g., 'what is a glob?'); answer directly.\n"
    "- Do not call tools if required arguments are missing; first ask a concise clarifying question.\n"
    "Pre-call checklist (enforce before calling):\n"
    "- file_pattern is present and looks like a pattern or filename (e.g., '*.py', 'report.*', 'notes.txt').\n"
    "- If base_path_key is provided, it must be one of: docs, downloads, desktop, pictures, videos, music.\n"
    "Output rules after any tool call:\n"
    "- Summarize results succinctly. If many items are returned, show only the top results and note the total.\n"
    "- For empty results, say 'No files found for that criteria.'\n"
    "Examples (for routing intuition):\n"
    "- User: 'Explain glob patterns' -> No tool call; provide explanation.\n"
    "- User: 'Find all *.py in docs' -> Call remote_file_search with file_pattern='*.py', base_path_key='docs'.\n"
    "- User: 'Search for report.*' (no location) -> Ask: 'Which base location? (docs/downloads/desktop/pictures/videos/music) or search all?'\n"
    "- User: 'show README.md from docs' -> Use show action with file_name='README.md', base_path_key='docs'.\n"
)

# --- 1. Define the LLM Tool (updated descriptions/schemas) ---
class FileSearchTool(BaseModel):
    """Search for files/folders on the remote server via gRPC.

    When to use: The user asks to locate files or folders by name or glob/pattern (e.g., *.py, report.*), optionally restricting to a known base directory.
    When NOT to use: The user is asking a general/conceptual question or has not provided enough information to form a file_pattern.

    Notes:
    - base_path_key, when provided, must be one of: 'docs', 'downloads', 'desktop', 'pictures', 'videos', 'music'.
    - If base_path_key is omitted, the server searches all allowed locations.
    - Set include_hidden true to include dotfiles and hidden folders.
    """

    file_pattern: str = Field(
        ..., description="Glob or filename to match (e.g., '*.py', 'report.*', 'main.go', 'notes.txt')."
    )
    base_path_key: Optional[Literal["docs", "downloads", "desktop", "pictures", "videos", "music"]] = Field(
        None,
        description=(
            "Restrict search to a specific known folder key. If omitted, searches all allowed paths."
        ),
    )
    include_hidden: bool = Field(
        False, description="Include hidden files and folders (those starting with '.')."
    )

# Retained for schema documentation purposes; we no longer bind LangChain tools directly.
def remote_file_search(file_pattern: str, base_path_key: Optional[str] = None, include_hidden: bool = False):
    """Search for files/folders. This is invoked by the client after routing, not by LangChain tool-calling."""
    pass

# --- 2. The gRPC Client Function (Debug Enabled) ---
def call_grpc_server(file_pattern: str, base_key: Optional[str], hidden: bool, *, verbose: bool = True):
    search_desc = f"in '{base_key}'" if base_key else "in *all allowed paths*"
    if verbose:
        print(f"\n--- DEBUG (gRPC): Attempting to connect to gRPC server at 'localhost:50051' ---")
    
    try:
        with grpc.insecure_channel('localhost:50051') as channel:
            stub = filesearch_pb2_grpc.FileSearcherStub(channel)
            
            request = filesearch_pb2.SearchRequest(  # type: ignore[attr-defined]
                base_path_key=base_key, 
                file_pattern=file_pattern,
                include_hidden=hidden
            )
            
            if verbose:
                print(f"--- DEBUG (gRPC): Connection successful. Sending request: {{pattern: '{file_pattern}', key: '{base_key}'}} ---")
            response = stub.SearchFiles(request)
            if verbose:
                print("--- DEBUG (gRPC): Server responded. ---")
            
            if response.error_message:
                if verbose:
                    print(f"❌ Server Error: {response.error_message}")
                return []
            
            if not response.found_files:
                if verbose:
                    print("\n✅ Server responded: No files found for that criteria.")
                return []

            total = len(response.found_files)
            if verbose:
                show_n = min(total, 50)
                print(f"\n✅ Server found {total} files (showing first {show_n}):")
                for f in response.found_files[:show_n]:
                    print(f"  - {f}")
                if total > show_n:
                    print(f"  ... and {total - show_n} more")
            return list(response.found_files)

    except grpc.RpcError as e:
        if verbose:
            print(f"\n❌ gRPC connection FAILED: {e.details()}")
            print("   Is the `search_server.py` script running in its own terminal?")
        return []
    except Exception as e:
        if verbose:
            print(f"\n❌ An unexpected error occurred in gRPC call: {e}")
        return []

# --- 3. The Main LLM Client Loop (Debug Enabled) ---
def main():
    print("--- DEBUG: Initializing Client ---")
    
    # --- THIS IS THE FIX ---
    ollama_base_url = "http://170.70.1.53:11434"
    # -----------------------

    try:
        print(f"--- DEBUG (LLM): Attempting to connect to Ollama Server at {ollama_base_url} ---")
        llm = OllamaLLM(base_url=ollama_base_url, model="llama3.2:latest", format="json")
        print("--- DEBUG (LLM): Ollama connection appears successful. ---")
    except Exception as e:
        print(f"\n❌ CRITICAL FAILURE: Could not initialize Ollama.")
        print(f"   Error: {e}")
        print(f"   Check that {ollama_base_url} is correct AND includes 'http://'")
        return

    print("🤖 LLM File Search Client is ready.")
    print("   (Type 'exit' or 'quit' to stop)")

    while True:
        try:
            query = input("\n> ")
            if query.lower() in ['exit', 'quit']:
                break
                
            print(f"--- DEBUG (LLM): Sending query to LLM: '{query}' ---")
            sys.stdout.flush() # Force print to show up
            
            # Build a single-turn prompt instructing JSON planning for actions
            allowed_keys = ["docs", "downloads", "desktop", "pictures", "videos", "music"]
            planning_instructions = f"""
{SYSTEM_POLICY}

You must decide one action: "search", "show", "answer", or "clarify".
- action="search": Use when the user wants to find files/folders. Provide search inputs.
- action="show": Use only when the user provided the exact name of a single file (no wildcards, no paths). You must return the file_name and optionally base_path_key/include_hidden so the client can search for that exact file and display its full content.
- action="answer": Use when the user asks a conceptual/explanatory question; provide a textual answer.
- action="clarify": Use when the user likely wants a search but didn't provide enough info; ask exactly one short clarifying question.

Output STRICT JSON only (no prose), following this schema:
{{
    "action": "search" | "show" | "answer" | "clarify",
    "search": {{
        "file_pattern": "string",
        "base_path_key": "one of {allowed_keys} or null",
        "include_hidden": true | false
    }},
    "show": {{
        "file_name": "string",  // exact filename only, e.g., "README.md"; no wildcards/paths
        "base_path_key": "one of {allowed_keys} or null",
        "include_hidden": true | false
    }},
    "answer": "string",
    "clarify": "string"
}}

Fill only the relevant field(s) matching the action. Return JSON only.

User Query: {query}
"""

            ai_raw = llm.invoke(planning_instructions)
            print("--- DEBUG (LLM): Raw JSON plan received. ---")

            # Parse JSON robustly
            plan: Dict[str, Any]
            try:
                plan = json.loads(ai_raw)
            except Exception:
                # Try to extract JSON object if any extra tokens slipped in
                start = ai_raw.find('{')
                end = ai_raw.rfind('}')
                if start != -1 and end != -1 and end > start:
                    try:
                        plan = json.loads(ai_raw[start:end+1])
                    except Exception:
                        plan = {"action": "answer", "answer": ai_raw}
                else:
                    plan = {"action": "answer", "answer": ai_raw}

            action = (plan.get("action") or "").lower()
            if action == "answer":
                print("\n🤖 Assistant:")
                print(f"   {plan.get('answer') or ''}")
                continue
            elif action == "clarify":
                print("\n🤖 Clarification needed:")
                print(f"   {plan.get('clarify') or 'Could you clarify your request?'}")
                continue
            elif action == "show":
                show_args = plan.get("show") or {}
                file_name = (
                    show_args.get("file_name")
                    or show_args.get("filename")
                    or show_args.get("name")
                    or show_args.get("file")
                )
                base_key = show_args.get("base_path_key")
                include_hidden = bool(show_args.get("include_hidden", False))

                # Validate filename: must be a simple filename, no paths or wildcards
                def _is_simple_filename(name: str) -> bool:
                    if not name or not isinstance(name, str):
                        return False
                    if any(sep in name for sep in ['\\', '/', ':']):
                        return False
                    if any(ch in name for ch in ['*', '?', '[', ']']):
                        return False
                    return True

                if not _is_simple_filename(file_name if isinstance(file_name, str) else ""):
                    # Fallback: try to extract a plausible filename from the user's query
                    candidate = None
                    # 1) Prefer quoted segments
                    quoted = re.findall(r'["\']([^"\']{1,255})["\']', query)
                    for q in quoted:
                        if _is_simple_filename(q):
                            candidate = q
                            break
                    # 2) Check whitespace tokens for something that looks like a filename with an extension
                    if candidate is None:
                        for tok in query.split():
                            if '.' in tok and _is_simple_filename(tok):
                                candidate = tok
                                break
                    if candidate is None:
                        print("\n🤖 Missing or invalid file_name for show action.")
                        continue
                    file_name = candidate
                # At this point we have a validated simple filename; enforce type for linters
                file_name = str(file_name)
                if any(sep in file_name for sep in ['\\', '/', ':']) or any(ch in file_name for ch in ['*', '?', '[', ']']):
                    print("\n🤖 'show' requires an exact filename (no paths or wildcards). Try action 'search' instead.")
                    continue
                if base_key is not None and base_key not in allowed_keys:
                    print("\n🤖 Invalid base_path_key for show. Allowed: docs/downloads/desktop/pictures/videos/music.")
                    continue

                # Search for candidate files without verbose printing
                candidates = call_grpc_server(
                    file_pattern=file_name,
                    base_key=base_key,
                    hidden=include_hidden,
                    verbose=False,
                )

                # Filter for exact filename matches (case-insensitive)
                fname_lower = file_name.lower()
                exact = [p for p in candidates if os.path.basename(p).lower() == fname_lower]

                if not exact:
                    print("\n🤖 No file found matching that exact name.")
                    if candidates:
                        # Show hints: top few similar paths
                        preview = candidates[:10]
                        print("   Did you mean one of these?")
                        for p in preview:
                            print(f"   - {p}")
                    continue
                if len(exact) > 1:
                    print("\n🤖 Multiple files matched that name; please be more specific using a base path key or different name:")
                    for p in exact[:20]:
                        print(f"   - {p}")
                    if len(exact) > 20:
                        print(f"   ... and {len(exact)-20} more")
                    continue

                # Exactly one match: read and display full content
                target = exact[0]
                try:
                    # Informative header
                    print(f"\n📄 Showing full content of: {target}")
                    size_bytes = None
                    try:
                        size_bytes = os.path.getsize(target)
                        print(f"   Size: {size_bytes} bytes")
                    except Exception:
                        pass
                    with open(target, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                    print("\n--- BEGIN FILE ---")
                    print(content)
                    print("--- END FILE ---\n")
                except Exception as e:
                    print(f"\n❌ Failed to read file: {e}")
                continue
            elif action == "search":
                search_args = plan.get("search") or {}
                file_pattern = search_args.get("file_pattern")
                base_key = search_args.get("base_path_key")
                include_hidden = bool(search_args.get("include_hidden", False))

                # Validate base_key
                if base_key is not None and base_key not in allowed_keys:
                    print("\n🤖 Invalid base_path_key returned by model. Allowed: docs/downloads/desktop/pictures/videos/music.")
                    continue
                if not file_pattern or not isinstance(file_pattern, str):
                    print("\n🤖 Missing or invalid file_pattern. Please provide a glob or filename.")
                    continue

                call_grpc_server(
                    file_pattern=file_pattern,
                    base_key=base_key,
                    hidden=include_hidden,
                )
                continue
            else:
                print("\n🤖 Unexpected planner action. Raw response:")
                print(f"   {ai_raw}")
                continue

        except Exception as e:
            print(f"\n❌ An error occurred in the client loop: {e}")
            print("   This may be a network error connecting to OLLAMA.")
            print(f"   Check your connection to {ollama_base_url}")

if __name__ == '__main__':
    main()