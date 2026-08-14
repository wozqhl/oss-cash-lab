"""Sample app with AI artifacts for ai-bom scan demo."""
import pickle

MODEL_ID = "huggingface.co/bert-base-uncased"
LOCAL_WEIGHTS = "./models/tiny-llama.gguf"
OPENAI_MODEL = "gpt-4o-mini"

def load_cache(path):
    # Forbidden pattern for --strict
    with open(path, "rb") as f:
        return pickle.load(f)

def main():
    print("model", MODEL_ID, LOCAL_WEIGHTS, OPENAI_MODEL)

if __name__ == "__main__":
    main()
