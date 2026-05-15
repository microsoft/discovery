#!/bin/bash

# az account set --subscription e5886ea0-4dac-4ab2-b608-b0d4a3101843
# az aks get-credentials --resource-group hack709-sc-mrg --name hack709-sc-aks --overwrite-existing
# kubelogin convert-kubeconfig -l azurecli

#az account set --subscription fdba8b3d-edfc-4058-bb5c-f8e137727c3e
#az aks get-credentials --resource-group alexukssc3-mrg --name alexukssc3-aks --overwrite-existing
#kubelogin convert-kubeconfig -l azurecli

#az account set --subscription fdba8b3d-edfc-4058-bb5c-f8e137727c3e
#az aks get-credentials --resource-group sc-autotest-sc2-mrg --name sc-autotest-sc2-aks --overwrite-existing
#kubelogin convert-kubeconfig -l azurecli

#az aks get-credentials --resource-group alzSC01-mrg --name alzsc01-aks --overwrite-existing
#kubelogin convert-kubeconfig -l azurecli

#az aks get-credentials --resource-group mrg-dscmp-matt-sc-test-dqfrqp --name matt-sc-test-aks --overwrite-existing
#kubelogin convert-kubeconfig -l azurecli

#az aks get-credentials --resource-group mrg-dscmp-sc-autotest-swe-pjm7ug --name aks-dscmp-pjm7 --overwrite-existing
#kubelogin convert-kubeconfig -l azurecli

az aks get-credentials --resource-group mrg-dscmp-sc-eastus-k191n1 --name sc-eastus-aks --overwrite-existing
kubelogin convert-kubeconfig -l azurecli
