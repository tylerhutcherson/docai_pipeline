# File overview:  Main DAG/workflow.  Performs the following:  
# - triggered on file deposit to the Invoice/inbox dir
# - Generates a worker pod per file for Azure OCR (Formrecognizer)
# - Generates a worker pod per OCR output for OpenAI embedding
# - Generates a worker pod per Embedding for Redis VSS disposition (process invoice or categorize as a duplicate)

from datetime import datetime
from airflow.decorators import dag, task
from kubernetes.client import models as k8s
from airflow.sensors.base import PokeReturnValue
from airflow.models import Variable
import os
import json
import logging
import pprint

# local host volume mount for the Invoices directory
executor_config_volume_mount = {
    "pod_override": k8s.V1Pod(
        spec=k8s.V1PodSpec(
            containers=[
                k8s.V1Container(
                    name="base",
                    volume_mounts=[
                        k8s.V1VolumeMount(mount_path="/opt/airflow/invoices", name="inv-vol")
                    ],
                )
            ],
            volumes=[
                k8s.V1Volume(
                    name="inv-vol",
                    persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(claim_name='invoice-claim')
                )
            ],
        )
    ),
}

# DAG decorator to establish work flow.  Non-scheduled dag/trigger to start.
@dag(dag_id="invoice-processor", schedule=None, start_date=datetime(2023,1,1), catchup=False) 


def invoice_flow():

    @task.sensor(task_id="check_inbox", mode="reschedule", timeout=10, executor_config=executor_config_volume_mount)
    def check_inbox() -> PokeReturnValue:
        """ File sensor for invoices inbox.  If files are detected in the inbox, a cascade processing tasks are triggered:
        OCR, Embed, Dedup.
        """
        storage_var = Variable.get("storage", deserialize_json=True, default_var=None)
        if (type(storage_var) != 'dict'):  # hack for an apparent bug in airflow
            storage_var = json.loads(storage_var)
        inbox_path = storage_var['inbox']

        inbox_files = list(map(lambda file: os.path.join(inbox_path, file), os.listdir(inbox_path)))  
        logging.info(f'Number of files to be processed: {len(inbox_files)}')      
        if len(inbox_files) > 0:
            return PokeReturnValue(is_done=True, xcom_value=inbox_files)
        else:
            return PokeReturnValue(is_done=False)
    
    @task(task_id='parse_invoice', executor_config=executor_config_volume_mount) 
    def parse_invoice(inbox_file: str) -> dict:
        """ OCR is performed on each of invoices in the inbox.  The result of OCR is space delimited string of a 
        configurable number of invoice fields.
        """
        from invoice.lib.ocr import ocr
        invoice = ocr(inbox_file)
        invoice['file'] = inbox_file
        logging.info(f'Invoice: {pprint.pformat(invoice)}')
        return invoice

    @task(task_id='embed_invoice')     
    def embed_invoice(invoice: dict) -> dict:
        """ Accepts a invoice dict that includes a text field of the OCR output
        and adds an OpenAI embedding (array of floats) to that dict

        """
        from invoice.lib.embed import get_embedding
        vector = get_embedding(invoice['ocr'])
        invoice['vector'] = vector
        logging.info(f'Invoice: {invoice["file"]}, Vector len: {invoice["vector"]}')
        return invoice
    
    @task(task_id='dedup_invoice', executor_config=executor_config_volume_mount)  
    def dedup_invoice(invoice: dict) -> None:
        """ Sends the invoice dict into a Redis VSS lookup to determine disposition - process or call it a duplicate
        """
        from invoice.lib.vss import dedup
        result = dedup(invoice)
        logging.info(f'Invoice: {invoice["file"]}, Result: {result}')
    
    dedup_invoice.expand(
        invoice=embed_invoice.expand(
            invoice=parse_invoice.expand(
                inbox_file=check_inbox()
            )
        )
    )
    
invoice_flow()