from fastapi import FastAPI
from pydantic import BaseModel
from app.utils import fetch_company_profile
from app.scoring import simple_score

app = FastAPI()

class ScoreQuery(BaseModel):
    ticker: str
    portfolio_value: float = 10000

@app.post('/score')
def score(q: ScoreQuery):
    prof = fetch_company_profile(q.ticker)
    # basic placeholders
    recent = {'7d': 0.02}
    sentiment = 0.0
    s = simple_score(prof, recent, sentiment)
    return {'ticker': q.ticker, 'score': s, 'profile': prof}
