from .tts import TTSManager
from .triage import UtteranceCategorizer
from .handlers import Clock, Weather

USER_AGENT = "custom-home-assistant (aaronbastian31@gmail.com)"


class CoreService:
    def __init__(self, voice:str='glados_classic'):
        self.tts_manager = TTSManager()
        self.tts = self.tts_manager.initialize_tts(voice)
        self.triager = UtteranceCategorizer()
        self.clock = Clock(user_agent=USER_AGENT)
        self.weather = Weather(user_agent=USER_AGENT)

    def handle_query(self, query: str, debug:bool = False):
        category, cleaned_query = self.triager.categorize(query)

        if category == "Other":
            response = self.llm_handle(cleaned_query)
        else:
            # get the class instance made to handle queries of this type.
            response = self.__getattribute__(category.lower()).handle_query(cleaned_query)

        if debug:
            for x in [category, cleaned_query, response]:
                print(x)
        
        return self.tts.synthesize(response['text'])
    
    def llm_handle(query:str):
        return ""