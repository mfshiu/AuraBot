from agentflow.core.agent import Agent

from logging import Logger
logger:Logger = __import__('src').get_logger()


class SummarizationAgent(Agent):
    def __init__(self, cfg):
        super().__init__(f'summarization.aurabot', cfg)


    def handle_text_extract(self, topic:str, file_info):
        logger.verbose(f"topic: {topic}, data: {file_info}")

        self._notify_children("TextExtract", file_info)
        
        
    def on_parent_message(self, _, info):
        if "TextExtract" == info['subject']:
            return child_info['data'] 
