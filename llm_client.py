import grpc
import sys # Import sys for flushing output
from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langchain_ollama.chat_models import ChatOllama
import filesearch_pb2
import filesearch_pb2_grpc

# --- 1. Define the LLM Tool (Unchanged) ---
class FileSearchTool(BaseModel):
    """A tool to search for files on the remote server."""
    file_pattern: str = Field(..., description="The wildcard pattern for the file, e.g., '*.py', 'report.*', 'main.go'.")
    base_path_key: Optional[str] = Field(None, description="The key for a *specific* search directory, e.g., 'projects', 'docs'. If not provided, *all* allowed directories will be searched.")
    include_hidden: bool = Field(False, description="Set to True to include hidden files and folders (those starting with '.').")

@tool(args_schema=FileSearchTool)
def remote_file_search(file_pattern: str, base_path_key: Optional[str] = None, include_hidden: bool = False):
    pass 

# --- 2. The gRPC Client Function (Debug Enabled) ---
def call_grpc_server(file_pattern: str, base_key: Optional[str], hidden: bool):
    search_desc = f"in '{base_key}'" if base_key else "in *all allowed paths*"
    print(f"\n--- DEBUG (gRPC): Attempting to connect to gRPC server at 'localhost:50051' ---")
    
    try:
        with grpc.insecure_channel('localhost:50051') as channel:
            stub = filesearch_pb2_grpc.FileSearcherStub(channel)
            
            request = filesearch_pb2.SearchRequest(
                base_path_key=base_key, 
                file_pattern=file_pattern,
                include_hidden=hidden
            )
            
            print(f"--- DEBUG (gRPC): Connection successful. Sending request: {{pattern: '{file_pattern}', key: '{base_key}'}} ---")
            response = stub.SearchFiles(request)
            print("--- DEBUG (gRPC): Server responded. ---")
            
            if response.error_message:
                print(f"❌ Server Error: {response.error_message}")
                return
            
            if not response.found_files:
                print("\n✅ Server responded: No files found matching that criteria.")
                return

            print(f"\n✅ Server found {len(response.found_files)} files:")
            for f in response.found_files:
                print(f"  - {f}")

    except grpc.RpcError as e:
        print(f"\n❌ gRPC connection FAILED: {e.details()}")
        print("   Is the `search_server.py` script running in its own terminal?")
    except Exception as e:
        print(f"\n❌ An unexpected error occurred in gRPC call: {e}")

# --- 3. The Main LLM Client Loop (Debug Enabled) ---
def main():
    print("--- DEBUG: Initializing Client ---")
    
    # --- THIS IS THE FIX ---
    ollama_base_url = "http://192.168.1.10:11434"
    # -----------------------

    try:
        print(f"--- DEBUG (LLM): Attempting to connect to Ollama Server at {ollama_base_url} ---")
        llm = ChatOllama(base_url=ollama_base_url, model="llama3.2:latest", format="json")
        llm_with_tools = llm.bind_tools([remote_file_search])
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
            
            # --- THIS IS THE LINE THAT WAS FAILING ---
            ai_msg = llm_with_tools.invoke(query)
            # ------------------------------------------

            print("--- DEBUG (LLM): Response received from LLM. ---")
            
            if not ai_msg.tool_calls:
                print("\n🤖 LLM did not understand a file search command. Try again.")
                print(f"   (Raw response: {ai_msg.content})")
                continue
                
            tool_call = ai_msg.tool_calls[0]
            print(f"--- DEBUG (LLM): LLM wants to call tool: {tool_call['name']} ---")
            if tool_call['name'] == "remote_file_search":
                args = tool_call['args']
                
                call_grpc_server(
                    file_pattern=args.get('file_pattern'),
                    base_key=args.get('base_path_key'),
                    hidden=args.get('include_hidden', False)
                )
            else:
                print(f"\n🤖 LLM called an unknown tool: {tool_call['name']}")

        except Exception as e:
            print(f"\n❌ An error occurred in the client loop: {e}")
            print("   This may be a network error connecting to OLLAMA.")
            print(f"   Check your connection to {ollama_base_url}")

if __name__ == '__main__':
    main()