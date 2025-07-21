from transformers import pipeline

class SentimentAnalyzer:
    def __init__(self):
        self.classifier = pipeline(
            "text-classification",
            model="distilbert-base-uncased-finetuned-sst-2-english",
            truncation=True
        )
    
    def analyze(self, text):
        try:
            result = self.classifier(text[:512])[0]
            return {
                'sentiment': result['label'].lower(),
                'confidence': result['score']
            }
        except Exception as e:
            return {'sentiment': 'neutral', 'confidence': 0.0}