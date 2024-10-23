from fastapi import FastAPI, File, UploadFile
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory, InMemoryChatMessageHistory
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from llava_custom import Custom_LLaVA
from pydantic import BaseModel
# import uvicorn
import torch
# from langchain.schema import LLMResult
from langchain_core.globals import set_llm_cache
from langchain_core.caches import InMemoryCache
import time
from datetime import datetime
import shutil
from xunfei import xunfei_recognize
from pathlib import Path
from contextlib import asynccontextmanager
from config import set_environment
from langchain_openai import ChatOpenAI
from pydub import AudioSegment


def delete_file(file_path):
    try:
        file = Path(file_path)
        if file.is_file(): 
            file.unlink()  
            print(f"File {file_path} is deleted successfully.")
        else:
            print(f"File {file_path} does not exist.")
    except Exception as e:
        print(f"File deleting error: {e}")


class RequestData(BaseModel):
    user_id: str
    time_span: str
    mode_code: int
    input_text: str
    image: str 


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("-"*50, "\nModel backend is starting up...\n", "-"*50)
    # initialize chatbot (local_model: 0, openai_api: 1)
    app.state.model_type = 1
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    if app.state.model_type == 0:
        model_path = r"G:\Research\ModelWeights\llava-v1.5-7b"
        model_name="llava-v1.5-7b"
        # Lora(set base model and adapter weights) 
        # base_path = "/workspace/LLaVA/PretrainedModel/llava-v1.5-7b"
        llm = Custom_LLaVA(model_path=model_path, 
                           model_base=None, 
                           model_name=model_name, 
                           load_4bit=False, 
                           load_8bit=True, 
                           device=device)
    else:
        set_environment()
        llm = ChatOpenAI(
                            model="gpt-4o-mini",
                            temperature=0,
                            max_tokens=None,
                            timeout=None,
                            max_retries=2
                        ) 
    # caching layer for chat models (reducing the number of API calls)
    set_llm_cache(InMemoryCache())
    # record history chat
    store = {}
    def get_session_history(session_id: str) -> BaseChatMessageHistory:
        if session_id not in store:
            store[session_id] = InMemoryChatMessageHistory()
        return store[session_id]

    with_message_history = RunnableWithMessageHistory(llm, get_session_history)
    config = {"configurable": {"session_id": "idx1"}}
    # initialize chat
    with_message_history.invoke([
                                    SystemMessage(content="A chat between a curious Human and an AI. The AI assistant gives helpful, detailed, and polite answers to the Human's questions."), 
                                    AIMessage(content="Hello! How can I help you today?"),
                                    HumanMessage(content="Hi! Nice to meet you.")
                                ], 
                                config=config)
    # initialize global resources
    app.state.chatbot = with_message_history
    app.state.config_history = config
    yield 
    print("-"*50, "\nModel backend is closing ...\n", "-"*50)
    del llm
    del with_message_history
    del device


app = FastAPI(lifespan=lifespan)


# convert .wav audio to texts
@app.post("/recognize")
async def upload_audio(file: UploadFile = File(...)):
    print(file)
    if not file.filename.endswith(('.wav', '.mp3')):
        return {"error": "File format not supported. Please upload a .wav or a .mp3 file."}
    print("-"*50, "\nAudio Recognize Start\n", "-"*50)
    # save audio file
    audio_path = f".\\audio_saved\\{file.filename}"
    with open(audio_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    # convert .wav to .mp3
    if file.filename.endswith(".wav"):
        # load .wav file
        audio = AudioSegment.from_wav(audio_path)
        # set sampling rate
        audio = audio.set_frame_rate(16000)
        audio_path0 = Path("audio_saved") / (file.filename.split('.')[0] + ".mp3")
        # export .mp3 audio file
        audio.export(audio_path0, format="mp3")
        # delete .wav file
        delete_file(audio_path)
        audio_path = audio_path0
    # recognize texts
    result, error_code = xunfei_recognize(audio_path)
    # delete audio file, release space
    delete_file(audio_path)
    print("Text:", result, "\nError Code:", error_code)
    print("-"*50, "\nAudio Recognize End\n", "-"*50)
    return {"output_text": result, "error_code": error_code}


@app.post("/model")
async def model_inference(data: RequestData):
    if data.mode_code == 0:
        chatbot = app.state.chatbot
        config = app.state.config_history
        prompt = ""
        # GPT and local model have different style prompt.
        if app.state.model_type == 0:
            if data.image != "":
                prompt += ("<image>" + data.input_text + "<img>" + data.image + "</img>")
            else:
                prompt += data.input_text
            message = HumanMessage(content=prompt)
        else:
            if data.image != "":
                message = HumanMessage(
                                        content=[
                                            {"type": "text", "text": data.input_text},
                                            {
                                                "type": "image_url",
                                                "image_url": {"url": f"data:image/jpeg;base64,{data.image}"},
                                            },
                                        ]
                                    )
            else:
                message = HumanMessage(content = data.input_text)
        print("-"*50, "\nModel Inference Start\n", "-"*50)
        print("\nuser_id: ", data.user_id, 
              "\ntime_span: ", data.time_span, 
              "\nmode_code: ", int(data.mode_code), 
              "\ninput_text: ", data.input_text, 
              "\nimage: ", data.image[-100:])
        start = time.time()
        response = chatbot.invoke(message, config=config)
        if app.state.model_type == 1:
            response = response.content
        end = time.time()
        print("Inference time: ", end - start)
        print("-"*50, "\nModel Inference End\n", "-"*50)
        # Extract response text from LLMResult object
        # full_text = get_response_text(response)
        return {"user_id": data.user_id, 
                "time_span": str(datetime.now()), 
                "mode_code": data.mode_code, 
                "output_text": response}
    elif data.mode_code == 1:
        pass
    elif data.mode_code == 2:
        pass
    elif data.mode_code == 3:
        pass
    else:
        pass

# def get_response_text(response: LLMResult) -> str:
#     full_text = ""
#     for generation in response.generations:
#         for gen in generation:
#             full_text += gen.text
#     return full_text


if __name__ == "__main__":
    # # initialize chatbot
    # device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    # model_path = r"G:\Research\ModelWeights\llava-v1.5-7b"
    # model_name="llava-v1.5-7b"
    # # base_path = "/workspace/LLaVA/PretrainedModel/llava-v1.5-7b"
    # llm = Custom_LLaVA(model_path=model_path, model_base=None, model_name=model_name, load_4bit=False, load_8bit=True, device=device)
    
    # # caching layer for chat models (reducing the number of API calls)
    # set_llm_cache(InMemoryCache())
    
    # # record history chat
    # store = {}
    # with_message_history = RunnableWithMessageHistory(llm, get_session_history)
    # config = {"configurable": {"session_id": "idx1"}}
    # response = with_message_history.invoke([
    #                                          SystemMessage(content="A chat between a curious Human and an AI. The AI assistant gives helpful, detailed, and polite answers to the Human's questions."), 
    #                                          AIMessage(content="Hello! How can I help you today?"),
    #                                          HumanMessage(content="Hi! Nice to meet you.")
    #                                        ], 
    #                                         config=config)



    # uvicorn.run(app, host="0.0.0.0", port=8000)
    pass
    
