import os
import fnmatch
from concurrent import futures
import time
import logging

import grpc
import filesearch_pb2
import filesearch_pb2_grpc

# --- NEW IMPORTS ---
try:
    from win32com.shell import shell, shellcon
except ImportError:
    print("ERROR: 'pywin32' library not found.")
    print("Please install it on the server: pip install pywin32")
    exit(1)
# --------------------


def _get_known_folder_path(folder_id):
    """
    Helper function to get a Windows known folder path by its FOLDERID constant.
    This is language-independent and the modern, correct API.
    """
    try:
        # SHGetKnownFolderPath(rfid, dwFlags, hToken)
        path = shell.SHGetKnownFolderPath(folder_id, 0, None)
        return path
    except Exception as e:
        logging.error(f"Failed to get known folder path for FOLDERID {folder_id}: {e}")
        return None

# --- THIS IS THE CRITICAL SECURITY SANDBOX (v4) ---
# This now uses the *modern* FOLDERID system, which is robust and correct.
# This fixes the 'CSIDL_DOWNLOADS' attribute error.
ALLOWED_PATHS = {
    "docs": _get_known_folder_path(shellcon.FOLDERID_Documents),
    "downloads": _get_known_folder_path(shellcon.FOLDERID_Downloads),
    "desktop": _get_known_folder_path(shellcon.FOLDERID_Desktop),
    "pictures": _get_known_folder_path(shellcon.FOLDERID_Pictures),
    "videos": _get_known_folder_path(shellcon.FOLDERID_Videos),
    "music": _get_known_folder_path(shellcon.FOLDERID_Music),
    # You can still add other custom paths
    # "projects": "D:\\MyProjects" 
}

# Filter out any paths that failed
ALLOWED_PATHS = {k: v for k, v in ALLOWED_PATHS.items() if v and os.path.isdir(v)}
# ----------------------------------------------


class FileSearcherServicer(filesearch_pb2_grpc.FileSearcherServicer):
    """
    Implements the FileSearcher gRPC service.
    (This class is unchanged from the previous version)
    """

    def _perform_search(self, root_dir, pattern, include_hidden):
        """Helper function to perform the recursive search in one directory."""
        found = []
        
        # Make pattern matching case-insensitive
        pattern_lower = pattern.lower()

        try:
            for root, dirs, files in os.walk(root_dir, topdown=True):
                if not include_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                    files = [f for f in files if not f.startswith('.')]

                for filename in files:
                    # Compare both as lowercase
                    if fnmatch.fnmatch(filename.lower(), pattern_lower):
                        full_path = os.path.join(root, filename)
                        found.append(full_path)
                        
                for dirname in dirs:
                    # Compare both as lowercase
                    if fnmatch.fnmatch(dirname.lower(), pattern_lower):
                        full_path = os.path.join(root, dirname)
                        found.append(full_path)
        except Exception as e:
            logging.warning(f"Error searching {root_dir}: {e}")
            pass 
        return found

    def SearchFiles(self, request, context):
        """
        The main RPC method. This is called by the client.
        """
        pattern = request.file_pattern
        include_hidden = request.include_hidden
        
        base_path_key = None
        if request.HasField('base_path_key'):
            # Make key matching case-insensitive
            base_path_key = request.base_path_key.lower()

        response = filesearch_pb2.SearchResponse()
        all_found_files = []
        
        if ".." in pattern or pattern.startswith(("/", "\\")):
            logging.warning(f"Client sent potentially malicious pattern: {pattern}")
            response.error_message = "Invalid pattern."
            return response

        if base_path_key:
            # --- 1. Search a SPECIFIC allowed path ---
            if base_path_key not in ALLOWED_PATHS:
                logging.warning(f"Client requested invalid base path key: {request.base_path_key} (normalized to: {base_path_key})")
                response.error_message = f"Invalid base path key. Allowed keys are: {list(ALLOWED_PATHS.keys())}"
                return response
            
            root_dir_to_search = ALLOWED_PATHS[base_path_key]
            logging.info(f"Starting specific search in '{root_dir_to_search}' for pattern '{pattern}'")
            all_found_files = self._perform_search(root_dir_to_search, pattern, include_hidden)
            
        else:
            # --- 2. Search ALL allowed paths (no key provided) ---
            logging.info(f"Starting global search for pattern '{pattern}' in all {len(ALLOWED_PATHS)} allowed paths.")
            for key, root_dir in ALLOWED_PATHS.items():
                logging.info(f"  ... searching in '{key}' ({root_dir})")
                try:
                    found_in_path = self._perform_search(root_dir, pattern, include_hidden)
                    all_found_files.extend(found_in_path)
                except Exception as e:
                    logging.warning(f"Failed to search {key}: {e}")

        response.found_files.extend(all_found_files)
        logging.info(f"Search complete. Found {len(all_found_files)} total files.")
        return response


def serve():
    """Starts the gRPC server."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    filesearch_pb2_grpc.add_FileSearcherServicer_to_server(
        FileSearcherServicer(), server
    )
    server.add_insecure_port('[::]:50051')
    print("🚀 'God-Level' File Search Server (v4) started on port 50051...")
    print("Found and allowed search paths:")
    if not ALLOWED_PATHS:
        print("  - WARNING: No known folders were found.")
    for key, path in ALLOWED_PATHS.items():
        print(f"  - '{key}' -> '{path}'")
    
    server.start()
    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        print("Stopping server...")
        server.stop(0)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    serve()