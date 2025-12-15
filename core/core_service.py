from .tts import TTSManager
from .triage import UtteranceCategorizer
from .handlers import Clock


class CoreService:
    def __init__(self, voice:str='glados_classic'):
        self.tts_manager = TTSManager()
        self.tts = self.tts_manager.initialize_tts(voice)
        self.triager = UtteranceCategorizer()
        self.clock = Clock()

    def handle_query(self, query: str):
        category: str = self.triager.categorize(query)

        if category == "Other":
            response = self.llm_handle(query)
        else:
            # get the class instance made to handle queries of this type.
            response = self.__getattribute__(category.lower()).handle_query(query)

        if response['success']:
            return self.tts.synthesize(response['text'])
        
    
    def llm_handle(query:str):
        return ""
    
    def clock(query:str):
        pass