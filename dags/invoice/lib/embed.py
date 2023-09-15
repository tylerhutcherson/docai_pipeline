import openai
from airflow.models import Variable
import json
from tenacity import ( retry, stop_after_attempt, wait_random_exponential )

openai_var = Variable.get("openai", deserialize_json=True, default_var=None)
if (type(openai_var) != 'dict'):  # hack for an apparent bug in airflow
    openai_var = json.loads(openai_var)

openai.api_type = openai_var["type"]
openai.api_key = openai_var["key"] 
openai.api_base =  openai_var["endpoint"] 
openai.api_version = openai_var["version"]

@retry(wait=wait_random_exponential(min=3, max=100), stop=stop_after_attempt(10))
def get_embedding(text: str) -> [float]:
    response = openai.Embedding.create(
        input=text,
        engine="EmbeddingModel"
    )
    return response['data'][0]['embedding']