class DataProvider:
    def __init__(self, broker):
        self.broker = broker

    async def get_option_chain(self, symbol: str):
        """Fetch the option chain for a given symbol asynchronously."""
        raise NotImplementedError("get_option_chain must be implemented by subclasses or injected broker.")

    async def get_history(self, symbol: str, strike: float, interval: str):
        """Fetch historical data for a given symbol, strike, and interval asynchronously."""
        raise NotImplementedError("get_history must be implemented by subclasses or injected broker.")
