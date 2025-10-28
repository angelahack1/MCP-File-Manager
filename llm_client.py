import grpc
from typing import Optional  # <-- Import Optional
from pydantic import BaseModel, Field # Use Pydantic v2
from langchain_core.tools import tool
from langchain_ollama.chat_models import ChatOllama

# Import the compiled gRPC files
import filesearch_pb2
import filesearch_pb2_grpc

# --- 1. Define the LLM Tool ---
# This class defines the *exact* parameters the LLM can extract.
class FileSearchTool(BaseModel):
    """A tool to search for files on the remote server."""
    file_pattern: str = Field(..., description="The wildcard pattern for the file, e.g., '*.py', 'report.*', 'main.go'.")
    base_path_key: Optional[str] = Field(None, description="The key for a *specific* search directory, e.g., 'projects', 'docs'. If not provided, *all* allowed directories will be searched.")
    include_hidden: bool = Field(False, description="Set to True to include hidden files and folders (those starting with '.').")

@tool(args_schema=FileSearchTool)
def remote_file_search(file_pattern: str, base_path_key: Optional[str] = None, include_hidden: bool = False) -> str:
    """
    This function is a STUB for the LLM. 
    It doesn't *do* the search; it just defines the tool.
    The *actual* search is done by the gRPC client below.
    """
    pass 

# --- 2. The gRPC Client Function ---
def call_grpc_server(file_pattern: str, base_key: Optional[str], hidden: bool):
    """
    Connects to the gRPC server and calls the SearchFiles RPC.
    """
    # Update the logging message
    search_desc = f"in '{base_key}'" if base_key else "in *all allowed paths*"
    print(f"\n📡 Connecting to gRPC server...")
    print(f"   Searching {search_desc} for '{file_pattern}' (hidden={hidden})...")
    
    try:
        with grpc.insecure_channel('localhost:50051') as channel:
            stub = filesearch_pb2_grpc.FileSearcherStub(channel)
            
            # Create the request. gRPC handles None for optional fields.
            request = filesearch_pb2.SearchRequest(
                base_path_key=base_key, 
                file_pattern=file_pattern,
                include_hidden=hidden
            )
            
            response = stub.SearchFiles(request)
            
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
        print(f"\n❌ gRPC connection failed: {e.details()}")
        print("   Is the `search_server.py` script running on the remote machine?")
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")

# --- 3. The Main LLM Client Loop ---
def main():
    """
    The main client loop.
    """
    print("Initializing Client-Side LLM...")
    # Initialize the LLM and bind the tool
    llm = ChatOllama(model="llama3.2:latest", format="json") # Assumes llama3 model
    llm_with_tools = llm.bind_tools([remote_file_search])
    
    print("🤖 LLM File Search Client is ready.")
    print("   (Type 'exit' or 'quit' to stop)")

    while True:
        try:
            query = input("\n> ")
            if query.lower() in ['exit', 'quit']:
                break
                
            print("🧠 LLM is thinking...")
            
            # Send the natural language query to the LLM
            ai_msg = llm_with_tools.invoke(query)
            
            if not ai_msg.tool_calls:
                print("\n🤖 LLM did not understand a file search command. Try again.")
                print(f"   (Raw response: {ai_msg.content})")
                continue
                
            # --- Tool call was extracted successfully! ---
            tool_call = ai_msg.tool_calls[0]
            if tool_call['name'] == "remote_file_search":
                args = tool_call['args']
                
                # Call the *actual* gRPC function with the args from the LLM
                call_grpc_server(
                    file_pattern=args.get('file_pattern'),
                    base_key=args.get('base_path_key'), # This will be None if not provided
                    hidden=args.get('include_hidden', False)
                )
            else:
                print(f"\n🤖 LLM called an unknown tool: {tool_call['name']}")

        except Exception as e:
            print(f"An error occurred in the client loop: {e}")

if __name__ == '__main__':
    main()