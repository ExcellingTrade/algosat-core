from fastapi import APIRouter, Depends, HTTPException
from algosat.api.auth_dependencies import get_current_user
from typing import Dict, Any
import requests

router = APIRouter(tags=["NSE Data"], dependencies=[Depends(get_current_user)])

def fetch_nse_json(url: str):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.76 Safari/537.36',
        "Upgrade-Insecure-Requests": "1", "DNT": "1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate"
    }
    try:
        response = requests.get(url, headers=headers, timeout=25)
        response.raise_for_status()
        return response.json()
    except Exception:
        return {}

@router.get("/getMarqueData")
def get_marque_data(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    API endpoint to fetch marquee data from NSE India.
    """
    url = "https://www.nseindia.com/api/NextApi/apiClient?functionName=getMarqueData"
    return fetch_nse_json(url)

@router.get("/getIndexData")
def get_index_data(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    API endpoint to fetch index data from NSE India.
    """
    url = "https://www.nseindia.com/api/NextApi/apiClient?functionName=getIndexData&&type=All"
    return fetch_nse_json(url)

@router.get("/getNseHolidayList")
def get_nse_holiday_list(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    API endpoint to fetch NSE trading holiday list.
    Returns a list of trading dates only.
    """
    url = "https://www.nseindia.com/api/holiday-master?type=trading"
    data = fetch_nse_json(url)
    holidays = []
    try:
        holidays = [d['tradingDate'] for d in data.get('CM', [])]
    except Exception:
        holidays = []
    return holidays
