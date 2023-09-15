#!/bin/bash

# delete resource group
az group delete \
    --name $USER-ai-services-resource-group \
    --yes

# delete openai resource
az cognitiveservices account purge \
    --name openai-resource \
    --resource-group $USER-ai-services-resource-group \
    --location eastus 

# delete ocr resource
az cognitiveservices account purge \
    --name formrecognizer-resource \
    --resource-group $USER-ai-services-resource-group \
    --location eastus 