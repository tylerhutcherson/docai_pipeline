import redis
from redis.commands.search.field import VectorField, TextField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType
from redis.commands.search.query import Query
import shutil
import json
from airflow.models import Variable
import numpy as np
import uuid
import logging
import os

def dedup(invoice: dict) -> str:
    """  Accepts a Python dict that includes a vector of a given invoice file.  That vector is then sent into
    Redis VSS to determine disposition.  If there's another invoice in Redis within a given vector distance of the input invoice, 
    this invoice is disposed as a duplicate moved to the 'dups' directory.  Otherwise, it is disposed as a net new invoice
    and moved to the 'processed' directory. 
    """
    re_var = Variable.get("re", deserialize_json=True, default_var=None)
    if (type(re_var) != 'dict'):  # hack for an apparent bug in airflow
        re_var = json.loads(re_var)
    
    storage_var = Variable.get("storage", deserialize_json=True, default_var=None)
    if (type(storage_var) != 'dict'):  # hack for an apparent bug in airflow
        storage_var = json.loads(storage_var)

    creds = redis.UsernamePasswordCredentialProvider(re_var['user'], re_var['pwd'])
    client = redis.Redis(host=re_var['host'], port=re_var['port'], credential_provider=creds)
    
    try:
        client.ft(re_var['vector_index']).info()
    except:
        idx_def = IndexDefinition(index_type=IndexType.HASH, prefix=[re_var['vector_prefix']])
        schema = [
            TextField('customer_name'),
            VectorField('vector',
                'HNSW', 
                { 'TYPE': re_var['vector_type'], 'DIM': re_var['vector_dim'], 'DISTANCE_METRIC': re_var['vector_metric'] }
            )
        ]
        client.ft(re_var['vector_index']).create_index(schema, definition=idx_def)
    
    vec = np.array(invoice['vector'], dtype=np.float32).tobytes()
    q = Query(f'@customer_name:({invoice["customer_name"]}) => [KNN 1 @vector $query_vec AS score]')\
            .return_fields('score')\
            .dialect(2) 
      
    results = client.ft(re_var['vector_index']).search(q, query_params={'query_vec': vec})
    docs = results.docs
    if len(docs) > 0 and 1 - float(docs[0].score) > re_var['vector_similarity_bound']:
        print(f'score:{float(docs[0].score)}')
        shutil.move(invoice['file'], storage_var['dups'])
        logging.info(f'Duplicate invoice:{os.path.basename(invoice["file"])}, Similarity:{round(1 - float(docs[0].score), 2)}')
        return 'duplicate'
    else:
        if len(docs) > 0:
            similarity = round(1 - float(docs[0].score), 2)
        else:
            similarity = 'N/A'
        
        client.hset(f'invoice:{uuid.uuid4()}', 
                    mapping={'customer_name': invoice['customer_name'], 'file': os.path.basename(invoice['file']),'vector': vec})
        shutil.move(invoice['file'], storage_var['processed'])
        logging.info(f'Processed invoice:{os.path.basename(invoice["file"])}, Similarity:{similarity}')
        return 'processed'