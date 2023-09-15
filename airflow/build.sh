#!/bin/bash

# Create a custom Airflow docker image that includes the Python modules used by the DAGs
if [ -z "$(docker image ls -q myairflow:2.7.1)" ]
then
    docker build -t myairflow:2.7.1 -f $PWD/airflow/Dockerfile .
fi

# Load that image on the Kind cluster
kind --name $USER-kind-cluster load docker-image myairflow:2.7.1

# Pull the helm chart for Airflow
if [ -z "$(helm repo list | grep apache-airflow)" ]
then
    helm repo add apache-airflow https://airflow.apache.org
fi
helm repo update apache-airflow

# Create PVs + PVCs for the local host storage locations - dags, logs, invoices
kubectl apply -f $PWD/airflow/airflow_volumes.yaml

# Deploy Airflow
helm install airflow apache-airflow/airflow -f $PWD/airflow/values.yaml --timeout 15m