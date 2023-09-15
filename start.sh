#!/bin/bash
# Usage: start.sh
# Description:  Builds a 3-worker K8S cluster.  Starts a 3-node Redis Enterpise cluster + Redis target DB, 
# builds an Airflow pipeline of Azure OCR, OpenAI embedding and Redis VSS.

echo -e "\n*** Deploy Kind Cluster ***"
./kind/build.sh

echo -e "\n*** Deploy Redis Operator ***"
kubectl create namespace re
kubectl config set-context --current --namespace=re
RE_LATEST=`curl --silent https://api.github.com/repos/RedisLabs/redis-enterprise-k8s-docs/releases/latest | grep tag_name | awk -F'"' '{print $4}'`
kubectl apply -f https://raw.githubusercontent.com/RedisLabs/redis-enterprise-k8s-docs/$RE_LATEST/bundle.yaml; sleep 1
kubectl rollout status deployment redis-enterprise-operator

echo -e "\n*** Deploy Redis Cluster ***"
REC_USER="demo@redis.com"
REC_PWD=$(apg -a 1 -m 20 -n 1 -M NCL)
echo "REC Username: $REC_USER"
echo "REC Password: $REC_PWD"
export REC_USER_B64=$(echo -n $REC_USER | base64)
export REC_PWD_B64=$(echo -n $REC_PWD | base64)
export REC_NAME=mycluster
envsubst < ./redis/rec.yaml | kubectl apply -f -; sleep 1
kubectl rollout status sts/$REC_NAME

echo -e "\n*** Deploy Redis Database ***"
export JSON_VERSION=`kubectl exec -it $REC_NAME-0 -c redis-enterprise-node -- \
curl -k -u "$REC_USER:$REC_PWD" https://localhost:9443/v1/modules | jq '.[] | select(.display_name=="RedisJSON").semantic_version' | tr -d '"'`

export SEARCH_VERSION=`kubectl exec -it $REC_NAME-0 -c redis-enterprise-node -- \
curl -k -u "$REC_USER:$REC_PWD" https://localhost:9443/v1/modules | jq '.[] | select(.display_name=="RediSearch 2").semantic_version' | tr -d '"'`

export REDB_USER="default"
export REDB_PWD=$(apg -a 1 -m 20 -n 1 -M NCL)
echo "REDB Username: $REDB_USER"
echo "REDB Password: $REDB_PWD"
export REDB_USER_B64=$(echo -n $REDB_USER | base64)
export REDB_PWD_B64=$(echo -n $REDB_PWD | base64)
export REDB_NAME="mydb"
export REDB_PORT=12000
envsubst < ./redis/redb.yaml | kubectl apply -f -
REDB_HOST=""
while [ -z $REDB_HOST ]
do
  sleep 3
  REDB_HOST=$(kubectl get service $REDB_NAME-load-balancer -o jsonpath='{.status.loadBalancer.ingress[0].*}' 2>/dev/null)
done
echo "REDB Host and Port: $REDB_HOST $REDB_PORT"

echo -e "\n*** Deploy Azure Cognitive Services ***"
./azure/build.sh

# JSON strings that will be saved to Airflow as Variables
re_json=$(echo \
'{
  "host":"'"$REDB_HOST"'",
  "port":"'"$REDB_PORT"'",
  "user":"'"$REDB_USER"'",
  "pwd":"'"$REDB_PWD"'",
  "vector_index":"invoice_idx",
  "vector_prefix":"invoice:",
  "vector_dim":1536,
  "vector_type":"FLOAT32",
  "vector_metric":"COSINE",
  "vector_similarity_bound":0.97
}' \
| tr -d '[:space:]')

storage_json=$(echo \
'{
  "dups":"/opt/airflow/invoices/dups",
  "inbox":"/opt/airflow/invoices/inbox",
  "processed":"/opt/airflow/invoices/processed"
}' \
| tr -d '[:space:]')

openai_json=$(echo \
'{
  "key":"'"$(az cognitiveservices account keys list \
    --name openai-resource \
    --resource-group $USER-ai-services-resource-group \
    | jq -r .key1)"'", 
  "endpoint":"'"$(az cognitiveservices account show \
    --name openai-resource \
    --resource-group  $USER-ai-services-resource-group \
    | jq -r .properties.endpoint)"'",
  "version":"2023-05-15",
  "type":"azure"
}' \
| tr -d '[:space:]')

formrec_json=$(echo \
'{
  "key":"'"$(az cognitiveservices account keys list \
    --name formrecognizer-resource \
    --resource-group $USER-ai-services-resource-group \
    | jq -r .key1)"'",
  "endpoint": "'"$(az cognitiveservices account show \
  --name formrecognizer-resource \
  --resource-group  $USER-ai-services-resource-group  \
  | jq -r .properties.endpoint)"'",
  "fields": ["InvoiceId","CustomerName","CustomerId","Items","InvoiceTotal","VendorName","PurchaseOrder"]
}' \
| tr -d '[:space:]')

echo -e "\n*** Deploy Airflow ***"
kubectl create namespace airflow
kubectl config set-context --current --namespace=airflow
./airflow/build.sh
kubectl -n airflow rollout status sts/airflow-triggerer
# set airflow variables with the JSON objects above
kubectl -n airflow -c triggerer exec -it airflow-triggerer-0 -- \
airflow variables set -j storage "$storage_json"
kubectl -n airflow -c triggerer exec -it airflow-triggerer-0 -- \
airflow variables set -j re "$re_json"
kubectl -n airflow -c triggerer exec -it airflow-triggerer-0 -- \
airflow variables set -j openai "$openai_json"
kubectl -n airflow -c triggerer exec -it airflow-triggerer-0 -- \
airflow variables set -j formrec "$formrec_json"

cp ./samples/* ./invoices/inbox
AIRFLOW_HOST=$(kubectl get service airflow-webserver -o jsonpath='{.status.loadBalancer.ingress[0].*}')

echo -e "\n*** Build Complete ***"
echo "K8s Cluster env:  kubectl get nodes"
echo "Redis K8s env:  kubectl -n re get all"
echo "Airflow K8s env: kubectl -n airflow get all"
echo "Airflow webserver: http://$AIRFLOW_HOST:8080"