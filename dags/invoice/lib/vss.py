import redis
import shutil
import json
import numpy as np
import uuid
import logging
import os

from airflow.models import Variable
from redisvl.index import SearchIndex
from redisvl.query import VectorQuery
from redisvl.query.filter import Tag


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
    index = SearchIndex.from_dict({
        "index": {
            "name": re_var['vector_index'],
            "prefix": re_var['vector_prefix'],
        },
        "fields": {
            "text": [{"name": "customer_name"}],
            "vector": [{
                    "name": "vector",
                    "dims": int(re_var['vector_dim']),
                    "distance_metric": re_var['vector_metric'],
                    "algorithm": "hnsw",
                    "datatype": re_var['vector_type']}
            ]
        },
    })
    index.set_client(client)
    # Create index if non-existent
    if not index.exists():
        index.create(overwrite=True)
    # VSS Query
    vec = np.array(invoice['vector'], dtype=np.float32).tobytes()
    customer_filter = (Tag("customer_name") == invoice["customer_name"])
    matches = index.query(
        VectorQuery(
            vector=vec,
            vector_field_name="vector",
            filter_expression=customer_filter,
            num_results=1,
            return_fields=["vector_distance"]
        )
    )
    # Process results
    similarity = 'N/A'
    if len(matches) > 0:
        score_ref = 1 - float(matches[0]['vector_distance'])
        similarity = round(score_ref, 2)
        # Bypass if record is a dupe
        if score_ref > re_var['vector_similarity_bound']:
            shutil.move(invoice['file'], storage_var['dups'])
            logging.info(f'Duplicate invoice:{os.path.basename(invoice["file"])}, Similarity:{similarity}')
            return 'duplicate'

    index.client.hset(
        key=f'invoice:{uuid.uuid4()}',
        mapping={
            'customer_name': invoice['customer_name'],
            'file': os.path.basename(invoice['file']),
            'vector': vec
        })
    shutil.move(invoice['file'], storage_var['processed'])
    logging.info(f'Processed invoice:{os.path.basename(invoice["file"])}, Similarity:{similarity}')
    return 'processed'