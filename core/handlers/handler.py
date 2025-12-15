class Handler:    
    def __init__(self):
        pass

    def handle_query(self, query:str):
        return self._respond(False, "handle_query for this class not set up")
    
    def _respond(self, success, text, data={}):
        return {
            "success": success,
            "text": text,
            "data": {}
        }