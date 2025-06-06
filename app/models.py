from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.preprocessing import LabelEncoder
from imblearn.over_sampling import ADASYN
import pandas as pd
import joblib
import os
import mlflow
import mlflow.sklearn
from elasticsearch import Elasticsearch
from datetime import datetime

def train_model(data_path, model_save_path):
    # Load dataset
    data = pd.read_csv(data_path)

    # Preprocess
    data.drop_duplicates(inplace=True)
    label_encoder = LabelEncoder()
    if 'GENDER' in data.columns:
        data['GENDER'] = label_encoder.fit_transform(data['GENDER'])
    if 'LUNG_CANCER' in data.columns:
        data['LUNG_CANCER'] = label_encoder.fit_transform(data['LUNG_CANCER'])
    data.replace({'YES': 2, 'NO': 1}, inplace=True)

    irrelevant_features = ['GENDER', 'AGE', 'SMOKING', 'SHORTNESS OF BREATH']
    df_new = data.drop(columns=irrelevant_features)
    df_new['ANXYELFIN'] = df_new['ANXIETY'] * df_new['YELLOW_FINGERS']

    # Oversample
    X = df_new.drop('LUNG_CANCER', axis=1)
    y = df_new['LUNG_CANCER']
    adasyn = ADASYN(random_state=42)
    X_resampled, y_resampled = adasyn.fit_resample(X, y)

    X_train, X_test, y_train, y_test = train_test_split(
        X_resampled, y_resampled, test_size=0.2, random_state=42
    )

    # Random Forest parameters
    rf_params = {
        'n_estimators': [100, 150],
        'max_depth': [5, 10, None],
        'min_samples_split': [2, 5],
        'min_samples_leaf': [1, 2],
        'bootstrap': [True, False]
    }

    # MLflow Tracking
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
    mlflow.set_experiment("Lung Cancer Prediction - Random Forest")

    with mlflow.start_run():
        grid_search = GridSearchCV(
            estimator=RandomForestClassifier(random_state=42),
            param_grid=rf_params,
            cv=5,
            scoring="accuracy",
            n_jobs=-1
        )
        grid_search.fit(X_train, y_train)

        best_model = grid_search.best_estimator_
        joblib.dump(best_model, model_save_path)

        mlflow.log_params(grid_search.best_params_)
        mlflow.log_metric("best_cv_accuracy", grid_search.best_score_)
        mlflow.sklearn.log_model(best_model, "model")

        # Elasticsearch Logging
        try:
            print("Connecting to Elasticsearch at http://host.docker.internal:9200")
            es = Elasticsearch("http://host.docker.internal:9200")

            if not es.ping():
                print("Elasticsearch connection failed.")
            else:
                print("Connected to Elasticsearch.")
                doc = {
                    "timestamp": datetime.utcnow(),
                    "model": "RandomForest",
                    "accuracy": grid_search.best_score_,
                    "params": grid_search.best_params_,
                    "source": "mlflow-rf-training"
                }
                print("Preparing to log this document:", doc)
                res = es.index(index="mlflow-metrics", document=doc)
                print("Logged to Elasticsearch successfully:", res)
        except Exception as e:
            print("Exception occurred while logging to Elasticsearch:", str(e))

    return {
        "accuracy": grid_search.best_score_,
        "best_params": grid_search.best_params_
    }
