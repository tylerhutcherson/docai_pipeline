#!/bin/bash

# create resource group
az group create \
    --name $USER-ai-services-resource-group \
    --location eastus

# create openai resource for embedding, S0/billable tier
az cognitiveservices account create \
    --name openai-resource \
    --resource-group $USER-ai-services-resource-group \
    --kind OpenAI --sku S0 --location eastus \
    --yes

# create openai deployment with a 'model'
az cognitiveservices account deployment create \
    --name openai-resource \
    --resource-group $USER-ai-services-resource-group \
    --deployment-name EmbeddingModel \
    --model-name text-embedding-ada-002 \
    --model-version "1"  \
    --model-format OpenAI \
    --sku-capacity "1" \
    --sku-name "Standard"


# create OCR resource, Free Tier
az cognitiveservices account create \
    --name formrecognizer-resource \
    --resource-group $USER-ai-services-resource-group \
    --kind FormRecognizer --sku F0 --location eastus \
    --yes