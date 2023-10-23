from azure.core.credentials import AzureKeyCredential
from azure.ai.formrecognizer import DocumentAnalysisClient, AnalyzedDocument
from airflow.models import Variable
import json
from tenacity import ( retry, stop_after_attempt, wait_random_exponential )

def stringify(invoice: AnalyzedDocument, vector_fields: [str]) -> str:
    """  Accepts a Azure Form Recognizer Document as input and then creates a space-separated
    string selected fields (configurable via Airflow Variable)
    """
    invoice_string = ''
    customer_name = ''
    for field_name in sorted(vector_fields):
        field = invoice.fields.get(field_name)
        value = ''
        if field:
            if field_name == 'Items':
                for idx, item in enumerate(field.value):
                    description = item.value.get('Description')
                    if description:
                        value += f'Description {description.value} '

                    quantity = item.value.get('Quantity')
                    if quantity:
                        value += f'Quantity {quantity.value} '

                    amount = item.value.get('Amount')
                    if amount:
                        value += f'Amount {amount.value} '
            else:
                value = str(field.value)
            value = value.replace('\n', ' ')
            value = value.replace('  ', ' ')
            invoice_string += f'{field_name} {value} '
        if field_name == 'CustomerName':
            if value:
                customer_name = value
            else:
                customer_name = 'unknown'
    return {'customer_name': customer_name, 'ocr': invoice_string}

@retry(wait=wait_random_exponential(min=10, max=60), stop=stop_after_attempt(3))
def ocr(filepath: str) -> dict:
    """ Executes Azure Form Recognized OCR and returns a Python dict that includes a text string
    of space-separated values from the input invoice.
    """
    formrec_var = Variable.get("formrec", deserialize_json=True, default_var=None)
    if (type(formrec_var) != 'dict'):  # hack for an apparent bug in airflow
        formrec_var = json.loads(formrec_var)

    key = formrec_var["key"]
    endpoint = formrec_var["endpoint"]
    vector_fields = formrec_var["fields"]
    client = DocumentAnalysisClient(endpoint=endpoint, credential=AzureKeyCredential(key))
    with open(filepath, "rb") as f:
        poller = client.begin_analyze_document("prebuilt-invoice", document=f, locale="en-US")

    invoice = (poller.result()).documents[0]
    return stringify(invoice, vector_fields)