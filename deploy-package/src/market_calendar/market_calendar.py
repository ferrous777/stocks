"""
Market Calendar implementation for trading day and holiday detection

This module provides comprehensive market calendar functionality including:
- US market holidays
- Trading day verification
- Market session times
- Extended hours handling
- Multi-timezone support
"""

from datetime import datetime, date, time, timedelta
from typing import List, Optional, Set, Dict, Tuple
from dataclasses import dataclass
from enum import Enum
import pytz
import logging

logger = logging.getLogger(__name__)


class MarketType(Enum):
    """Supported market types"""
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"
    CME = "CME"  # Futures
    FOREX = "FOREX"


class SessionType(Enum):
    """Market session types"""
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"
    EXTENDED = "extended"  # Combined pre + regular + after


@dataclass
class MarketSession:
    """Market session information"""
    market_type: MarketType
    session_type: SessionType
    start_time: time
    end_time: time
    timezone: str
    
    def is_open(self, current_time: datetime) -> bool:
        """Check if market is open at given time"""
        # Convert to market timezone
        market_tz = pytz.timezone(self.timezone)
        if current_time.tzinfo is None:
            current_time = pytz.utc.localize(current_time)
        
        market_time = current_time.astimezone(market_tz)
        current_time_only = market_time.time()
        
        return self.start_time <= current_time_only <= self.end_time


@dataclass
class TradingDay:
    """Trading day information"""
    date: date
    is_trading_day: bool
    market_type: MarketType
    sessions: List[MarketSession]
    early_close: Optional[time] = None
    note: Optional[str] = None


class MarketCalendar:
    """Main market calendar class for trading day and holiday management"""
    
    def __init__(self, market_type: MarketType = MarketType.NYSE):
        self.market_type = market_type
        self.timezone = self._get_market_timezone()
        self.sessions = self._get_market_sessions()
        
        # Cache for holidays
        self._holiday_cache: Dict[int, Set[date]] = {}
        
    def _get_market_timezone(self) -> str:
        """Get timezone for market type"""
        timezone_map = {
            MarketType.NYSE: "America/New_York",
            MarketType.NASDAQ: "America/New_York", 
            MarketType.CME: "America/Chicago",
            MarketType.FOREX: "UTC"
        }
        return timezone_map.get(self.market_type, "America/New_York")
    
    def _get_market_sessions(self) -> Dict[SessionType, MarketSession]:
        """Get trading sessions for market type"""
        if self.market_type in [MarketType.NYSE, MarketType.NASDAQ]:
            return {
                SessionType.PRE_MARKET: MarketSession(
                    market_type=self.market_type,
                    session_type=SessionType.PRE_MARKET,
                    start_time=time(4, 0),  # 4:00 AM
                    end_time=time(9, 30),   # 9:30 AM
                    timezone=self.timezone
                ),
                SessionType.REGULAR: MarketSession(
                    market_type=self.market_type,
                    session_type=SessionType.REGULAR,
                    start_time=time(9, 30),  # 9:30 AM
                    end_time=time(16, 0),    # 4:00 PM
                    timezone=self.timezone
                ),
                SessionType.AFTER_HOURS: MarketSession(
                    market_type=self.market_type,
                    session_type=SessionType.AFTER_HOURS,
                    start_time=time(16, 0),  # 4:00 PM
                    end_time=time(20, 0),    # 8:00 PM
                    timezone=self.timezone
                )
            }
        elif self.market_type == MarketType.CME:
            return {
                SessionType.REGULAR: MarketSession(
                    market_type=self.market_type,
                    session_type=SessionType.REGULAR,
                    start_time=time(8, 30),  # 8:30 AM CT
                    end_time=time(15, 15),   # 3:15 PM CT
                    timezone=self.timezone
                )
            }
        elif self.market_type == MarketType.FOREX:
            return {
                SessionType.EXTENDED: MarketSession(
                    market_type=self.market_type,
                    session_type=SessionType.EXTENDED,
                    start_time=time(22, 0),  # Sunday 10:00 PM UTC
                    end_time=time(22, 0),    # Friday 10:00 PM UTC
                    timezone=self.timezone
                )
            }
        
        return {}
    
    def _get_us_market_holidays(self, year: int) -> Set[date]:
        """Get US market holidays for a given year"""
        if year in self._holiday_cache:
            return self._holiday_cache[year]
        
        holidays = set()
        
        # New Year's Day
        new_years = date(year, 1, 1)
        if new_years.weekday() == 5:  # Saturday
            holidays.add(date(year, 1, 3))  # Observed Monday
        elif new_years.weekday() == 6:  # Sunday
            holidays.add(date(year, 1, 2))  # Observed Monday
        else:
            holidays.add(new_years)
        
        # Martin Luther King Jr. Day (3rd Monday in January)
        jan_1 = date(year, 1, 1)
        days_to_add = (7 - jan_1.weekday()) % 7 + 14  # 3rd Monday
        holidays.add(jan_1 + timedelta(days=days_to_add))
        
        # Presidents' Day (3rd Monday in February)
        feb_1 = date(year, 2, 1)
        days_to_add = (7 - feb_1.weekday()) % 7 + 14  # 3rd Monday
        holidays.add(feb_1 + timedelta(days=days_to_add))
        
        # Good Friday (Friday before Easter)
        easter = self._calculate_easter(year)
        good_friday = easter - timedelta(days=2)
        holidays.add(good_friday)
        
        # Memorial Day (last Monday in May)
        may_31 = date(year, 5, 31)
        days_to_subtract = (may_31.weekday() - 0) % 7  # Last Monday
        memorial_day = may_31 - timedelta(days=days_to_subtract)
        holidays.add(memorial_day)
        
        # Juneteenth (June 19th, starting 2021)
        if year >= 2021:
            juneteenth = date(year, 6, 19)
            if juneteenth.weekday() == 5:  # Saturday
                holidays.add(date(year, 6, 18))  # Observed Friday
            elif juneteenth.weekday() == 6:  # Sunday
                holidays.add(date(year, 6, 20))  # Observed Monday
            else:
                holidays.add(juneteenth)
        
        # Independence Day
        july_4 = date(year, 7, 4)
        if july_4.weekday() == 5:  # Saturday
            holidays.add(date(year, 7, 3))  # Observed Friday
        elif july_4.weekday() == 6:  # Sunday
            holidays.add(date(year, 7, 5))  # Observed Monday
        else:
            holidays.add(july_4)
        
        # Labor Day (1st Monday in September)
        sep_1 = date(year, 9, 1)
        days_to_add = (7 - sep_1.weekday()) % 7  # 1st Monday
        holidays.add(sep_1 + timedelta(days=days_to_add))
        
        # Thanksgiving (4th Thursday in November)
        nov_1 = date(year, 11, 1)
        # Find first Thursday
        days_to_add = (3 - nov_1.weekday()) % 7
        first_thursday = nov_1 + timedelta(days=days_to_add)
        thanksgiving = first_thursday + timedelta(days=21)  # 4th Thursday
        holidays.add(thanksgiving)
        
        # Christmas Day
        christmas = date(year, 12, 25)
        if christmas.weekday() == 5:  # Saturday
            holidays.add(date(year, 12, 24))  # Observed Friday
        elif christmas.weekday() == 6:  # Sunday
            holidays.add(date(year, 12, 26))  # Observed Monday
        else:
            holidays.add(christmas)
        
        # Cache the result
        self._holiday_cache[year] = holidays
        return holidays
    
    def _calculate_easter(self, year: int) -> date:
        """Calculate Easter date using the algorithm"""
        # Anonymous Gregorian algorithm
        a = year % 19
        b = year // 100
        c = year % 100
        d = b // 4
        e = b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i = c // 4
        k = c % 4
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month = (h + l - 7 * m + 114) // 31
        day = ((h + l - 7 * m + 114) % 31) + 1
        return date(year, month, day)
    
    def is_trading_day(self, check_date: date) -> bool:
        """Check if a given date is a trading day"""
        # Check if it's a weekend
        if check_date.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False
        
        # Check if it's a holiday
        holidays = self._get_us_market_holidays(check_date.year)
        return check_date not in holidays
    
    def get_trading_day_info(self, check_date: date) -> TradingDay:
        """Get detailed trading day information"""
        is_trading = self.is_trading_day(check_date)
        
        # Check for early closes (day after Thanksgiving, Christmas Eve, etc.)
        early_close = None
        note = None
        
        if is_trading:
            # Day after Thanksgiving
            holidays = self._get_us_market_holidays(check_date.year)
            for holiday in holidays:
                # Check if this is the day after Thanksgiving
                if holiday.month == 11 and holiday.weekday() == 3:  # Thanksgiving Thursday
                    day_after = holiday + timedelta(days=1)
                    if check_date == day_after:
                        early_close = time(13, 0)  # 1:00 PM
                        note = "Early close (day after Thanksgiving)"
                        break
                
                # Christmas Eve and July 3rd (if July 4th is on weekend)
                if ((holiday.month == 12 and holiday.day == 25) or 
                    (holiday.month == 7 and holiday.day == 4)):
                    day_before = holiday - timedelta(days=1)
                    if check_date == day_before and day_before.weekday() < 5:
                        early_close = time(13, 0)  # 1:00 PM
                        note = f"Early close (day before {holiday.strftime('%B %d')})"
                        break
        
        return TradingDay(
            date=check_date,
            is_trading_day=is_trading,
            market_type=self.market_type,
            sessions=list(self.sessions.values()) if is_trading else [],
            early_close=early_close,
            note=note
        )
    
    def get_next_trading_day(self, from_date: date) -> date:
        """Get the next trading day after the given date"""
        next_date = from_date + timedelta(days=1)
        while not self.is_trading_day(next_date):
            next_date += timedelta(days=1)
        return next_date
    
    def get_previous_trading_day(self, from_date: date) -> date:
        """Get the previous trading day before the given date"""
        prev_date = from_date - timedelta(days=1)
        while not self.is_trading_day(prev_date):
            prev_date -= timedelta(days=1)
        return prev_date
    
    def get_trading_days_between(self, start_date: date, end_date: date) -> List[date]:
        """Get all trading days between two dates (inclusive)"""
        trading_days = []
        current_date = start_date
        
        while current_date <= end_date:
            if self.is_trading_day(current_date):
                trading_days.append(current_date)
            current_date += timedelta(days=1)
        
        return trading_days
    
    def is_market_open(self, check_time: datetime, session_type: SessionType = SessionType.REGULAR) -> bool:
        """Check if market is open at a specific time"""
        check_date = check_time.date()
        
        # First check if it's a trading day
        if not self.is_trading_day(check_date):
            return False
        
        # Check if the session is active
        if session_type in self.sessions:
            session = self.sessions[session_type]
            return session.is_open(check_time)
        
        return False
    
    def get_market_hours(self, check_date: date) -> Dict[SessionType, Tuple[datetime, datetime]]:
        """Get market hours for a specific date"""
        if not self.is_trading_day(check_date):
            return {}
        
        market_tz = pytz.timezone(self.timezone)
        hours = {}
        
        trading_day_info = self.get_trading_day_info(check_date)
        
        for session_type, session in self.sessions.items():
            start_dt = market_tz.localize(
                datetime.combine(check_date, session.start_time)
            )
            
            # Handle early close
            if session_type == SessionType.REGULAR and trading_day_info.early_close:
                end_dt = market_tz.localize(
                    datetime.combine(check_date, trading_day_info.early_close)
                )
            else:
                end_dt = market_tz.localize(
                    datetime.combine(check_date, session.end_time)
                )
            
            hours[session_type] = (start_dt, end_dt)
        
        return hours


# Convenience functions
def is_trading_day(check_date: date, market_type: MarketType = MarketType.NYSE) -> bool:
    """Check if a date is a trading day"""
    calendar = MarketCalendar(market_type)
    return calendar.is_trading_day(check_date)


def get_next_trading_day(from_date: date, market_type: MarketType = MarketType.NYSE) -> date:
    """Get next trading day"""
    calendar = MarketCalendar(market_type)
    return calendar.get_next_trading_day(from_date)


def get_previous_trading_day(from_date: date, market_type: MarketType = MarketType.NYSE) -> date:
    """Get previous trading day"""
    calendar = MarketCalendar(market_type)
    return calendar.get_previous_trading_day(from_date)


def get_market_hours_today(market_type: MarketType = MarketType.NYSE) -> Dict[SessionType, Tuple[datetime, datetime]]:
    """Get today's market hours"""
    calendar = MarketCalendar(market_type)
    return calendar.get_market_hours(date.today())


def is_market_open_now(market_type: MarketType = MarketType.NYSE, 
                      session_type: SessionType = SessionType.REGULAR) -> bool:
    """Check if market is open right now"""
    calendar = MarketCalendar(market_type)
    return calendar.is_market_open(datetime.now(), session_type)
