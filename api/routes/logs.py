"""
Log management API rou# Constants
LOGS_BASE_DIR = Path("/opt/algosat/logs")
MAX_LOG_RETENTION_DAYS = 30  # Extended from 7 to 30 days
LOG_PATTERNS = {
    "rollover": r"(api|algosat|broker_monitor)\.log\.(\d{4}-\d{2}-\d{2})",  # Rotated files
    "api": r"api\.log",
    "algosat": r"algosat\.log", 
    "broker-monitor": r"broker_monitor\.log",
    # Legacy patterns for backward compatibility
    "legacy-rollover": r"(api|algosat|broker_monitor)-(\d{4}-\d{2}-\d{2})\.log\.(\d+)",
    "legacy-api": r"api-(\d{4}-\d{2}-\d{2})\.log",
    "legacy-algosat": r"algosat-(\d{4}-\d{2}-\d{2})\.log",
    "legacy-broker": r"broker_monitor-(\d{4}-\d{2}-\d{2})\.log",
}lgoSat trading system.
Provides endpoints for viewing, filtering, and streaming logs.
"""
import asyncio
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any, AsyncGenerator
import aiofiles
import json

from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from algosat.common.logger import get_logger
from ..auth_dependencies import get_current_user

logger = get_logger("api.logs")

router = APIRouter()

# Constants
LOGS_BASE_DIR = Path("/opt/algosat/logs")
MAX_LOG_RETENTION_DAYS = 30  # Extended from 7 to 30 days
LOG_PATTERNS = {
    "rollover": r"(api|algosat|broker_monitor)-(\d{4}-\d{2}-\d{2})\.log\.(\d+)",  # Check rollover first
    "api": r"api-(\d{4}-\d{2}-\d{2})\.log",
    "algosat": r"algosat-(\d{4}-\d{2}-\d{2})\.log",
    "broker-monitor": r"broker_monitor-(\d{4}-\d{2}-\d{2})\.log",  # Note: underscore in filename, hyphen in type
}

# In-memory store for streaming sessions (in production, use Redis or similar)
STREAMING_SESSIONS: Dict[str, Dict[str, Any]] = {}

class LogFile(BaseModel):
    """Log file information"""
    name: str
    path: str
    size: int
    modified: datetime
    type: str  # 'api', 'algosat', 'rollover'
    date: str

class LogEntry(BaseModel):
    """Individual log entry"""
    timestamp: datetime
    level: str
    logger: str
    module: str
    line: int
    message: str
    raw: str

class LogResponse(BaseModel):
    """Log response with metadata"""
    files: List[LogFile]
    total_size: int
    date_range: Dict[str, str]

class LogStreamResponse(BaseModel):
    """Real-time log stream response"""
    entry: LogEntry
    file: str
    position: int

# Utility functions
def parse_log_line(line: str) -> Optional[LogEntry]:
    """Parse a single log line into structured data"""
    try:
        # Pattern: 2025-06-06 05:04:43 - api.app - enhanced_app.py:64 - INFO - Starting Algosat API consumer service
        pattern = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - ([^-]+) - ([^:]+):(\d+) - (\w+) - (.+)"
        match = re.match(pattern, line.strip())
        
        if match:
            timestamp_str, logger_name, module, line_num, level, message = match.groups()
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            
            return LogEntry(
                timestamp=timestamp,
                level=level,
                logger=logger_name.strip(),
                module=module.strip(),
                line=int(line_num),
                message=message.strip(),
                raw=line.strip()
            )
    except Exception as e:
        logger.warning(f"Failed to parse log line: {e}")
    
    return None

def get_log_files_for_date(date: str) -> List[LogFile]:
    """Get all log files for a specific date"""
    log_files = []
    
    try:
        # Check if date directory exists first
        date_dir = LOGS_BASE_DIR / date
        if date_dir.exists() and date_dir.is_dir():
            # Search in date-specific directory
            for log_file in date_dir.glob("*.log*"):
                if log_file.is_file():
                    try:
                        stat = log_file.stat()
                        # Determine log type from filename - only include application logs for UI
                        if log_file.name == "api.log":
                            log_type = "api"
                        elif log_file.name == "algosat.log":
                            log_type = "algosat"
                        elif log_file.name == "broker_monitor.log":
                            log_type = "broker-monitor"
                        elif log_file.name.startswith("api-") and log_file.name.endswith(".log"):
                            # Legacy format: api-2025-07-18.log
                            log_type = "api"
                        elif log_file.name.startswith("algosat-") and log_file.name.endswith(".log"):
                            # Legacy format: algosat-2025-07-18.log
                            log_type = "algosat"
                        elif log_file.name.startswith("broker_monitor-") and log_file.name.endswith(".log"):
                            # Legacy format: broker_monitor-2025-07-18.log
                            log_type = "broker-monitor"
                        else:
                            # Skip PM2 logs and other files - don't show in UI
                            continue
                        
                        log_files.append(LogFile(
                            name=log_file.name,
                            path=str(log_file),
                            size=stat.st_size,
                            modified=datetime.fromtimestamp(stat.st_mtime),
                            type=log_type,
                            date=date
                        ))
                    except (OSError, IOError) as e:
                        logger.warning(f"Cannot access log file {log_file}: {e}")
                        continue
        
        # Also search for files with date in filename in base directory
        for log_file in LOGS_BASE_DIR.rglob("*.log*"):
            if not log_file.is_file():
                continue
                
            # Skip files already found in date directory
            if log_file.parent == date_dir:
                continue
                
            file_matched = False
            for pattern_name, pattern in LOG_PATTERNS.items():
                match = re.match(pattern, log_file.name)
                if match:
                    if pattern_name == "rollover":
                        # For rollover files: (api|algosat)-(\d{4}-\d{2}-\d{2})\.log\.(\d+)
                        file_type = match.group(1)  # api or algosat
                        file_date = match.group(2)  # date
                        rollover_num = match.group(3)  # rollover number
                        if file_date == date:
                            try:
                                stat = log_file.stat()
                                log_files.append(LogFile(
                                    name=log_file.name,
                                    path=str(log_file),
                                    size=stat.st_size,
                                    modified=datetime.fromtimestamp(stat.st_mtime),
                                    type="rollover",
                                    date=file_date
                                ))
                                file_matched = True
                            except (OSError, IOError) as e:
                                logger.warning(f"Cannot access log file {log_file}: {e}")
                                continue
                    else:
                        # For regular files: (api|algosat)-(\d{4}-\d{2}-\d{2})\.log
                        file_date = match.group(1)
                        if file_date == date:
                            try:
                                stat = log_file.stat()
                                log_files.append(LogFile(
                                    name=log_file.name,
                                    path=str(log_file),
                                    size=stat.st_size,
                                    modified=datetime.fromtimestamp(stat.st_mtime),
                                    type=pattern_name,
                                    date=file_date
                                ))
                                file_matched = True
                            except (OSError, IOError) as e:
                                logger.warning(f"Cannot access log file {log_file}: {e}")
                                continue
                    
                    # Break out of pattern loop once we find a match
                    if file_matched:
                        break
    except Exception as e:
        logger.error(f"Error getting log files for date {date}: {e}")
    
    return sorted(log_files, key=lambda x: x.modified)

def get_available_log_dates() -> List[str]:
    """Get list of available log dates based on existing date directories"""
    dates = set()
    cutoff_date = datetime.now() - timedelta(days=MAX_LOG_RETENTION_DAYS)
    
    try:
        # First, check for date directories (YYYY-MM-DD format)
        if LOGS_BASE_DIR.exists():
            for item in LOGS_BASE_DIR.iterdir():
                if item.is_dir():
                    try:
                        # Check if directory name matches YYYY-MM-DD format
                        log_date = datetime.strptime(item.name, "%Y-%m-%d")
                        if log_date >= cutoff_date:
                            # Only add if directory contains log files
                            if any(item.glob("*.log*")):
                                dates.add(item.name)
                    except ValueError:
                        continue
        
        # Also check for log files in root directory (legacy support)
        for log_file in LOGS_BASE_DIR.rglob("*.log*"):
            for pattern_name, pattern in LOG_PATTERNS.items():
                match = re.match(pattern, log_file.name)
                if match:
                    if pattern_name == "rollover":
                        # For rollover files: (api|algosat)-(\d{4}-\d{2}-\d{2})\.log\.(\d+)
                        date_str = match.group(2)  # date is group 2 for rollover
                    else:
                        # For regular files: (api|algosat)-(\d{4}-\d{2}-\d{2})\.log
                        date_str = match.group(1)  # date is group 1 for regular
                    
                    try:
                        # Use the date from the filename, not file modification time
                        log_date = datetime.strptime(date_str, "%Y-%m-%d")
                        # Only check retention against the date in filename, not file modification time
                        if log_date >= cutoff_date:
                            dates.add(date_str)
                    except ValueError:
                        continue
                    break  # Stop checking patterns once we find a match
    except Exception as e:
        logger.error(f"Error getting available log dates: {e}")
    
    return sorted(list(dates), reverse=True)

async def cleanup_old_logs():
    """Remove log files older than retention period"""
    cutoff_date = datetime.now() - timedelta(days=MAX_LOG_RETENTION_DAYS)
    deleted_count = 0
    
    try:
        for log_file in LOGS_BASE_DIR.rglob("*.log*"):
            if log_file.stat().st_mtime < cutoff_date.timestamp():
                log_file.unlink()
                deleted_count += 1
                logger.info(f"Deleted old log file: {log_file.name}")
    except Exception as e:
        logger.error(f"Error during log cleanup: {e}")
    
    return deleted_count

def create_streaming_session(user_id: str, log_type: str, level: Optional[str] = None) -> str:
    """Create a temporary streaming session for authenticated user"""
    session_id = str(uuid.uuid4())
    expiry = datetime.now() + timedelta(minutes=30)  # 30-minute expiry
    
    STREAMING_SESSIONS[session_id] = {
        "user_id": user_id,
        "log_type": log_type,
        "level": level,
        "expires_at": expiry,
        "created_at": datetime.now()
    }
    
    # Clean up expired sessions
    current_time = datetime.now()
    expired_sessions = [
        sid for sid, session in STREAMING_SESSIONS.items()
        if session["expires_at"] < current_time
    ]
    for sid in expired_sessions:
        del STREAMING_SESSIONS[sid]
    
    logger.info(f"Created streaming session {session_id} for user {user_id}")
    return session_id

def validate_streaming_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Validate streaming session and return session data"""
    session = STREAMING_SESSIONS.get(session_id)
    if not session:
        return None
    
    if session["expires_at"] < datetime.now():
        del STREAMING_SESSIONS[session_id]
        return None
    
    return session

# API Routes
@router.get("/", response_model=LogResponse)
async def get_log_overview(
    current_user: dict = Depends(get_current_user)
):
    """Get overview of available log files"""
    try:
        available_dates = get_available_log_dates()
        all_files = []
        total_size = 0
        
        for date in available_dates:
            files = get_log_files_for_date(date)
            all_files.extend(files)
            total_size += sum(f.size for f in files)
        
        date_range = {
            "start": available_dates[-1] if available_dates else "",
            "end": available_dates[0] if available_dates else ""
        }
        
        return LogResponse(
            files=all_files,
            total_size=total_size,
            date_range=date_range
        )
    except Exception as e:
        logger.error(f"Error getting log overview: {e}")
        raise HTTPException(status_code=500, detail="Failed to get log overview")

@router.get("/dates")
async def get_log_dates(
    current_user: dict = Depends(get_current_user)
):
    """Get list of available log dates"""
    try:
        dates = get_available_log_dates()
        return {"dates": dates}
    except Exception as e:
        logger.error(f"Error getting log dates: {e}")
        raise HTTPException(status_code=500, detail="Failed to get log dates")

@router.get("/files/{date}")
async def get_log_files(
    date: str,
    current_user: dict = Depends(get_current_user)
):
    """Get log files for a specific date"""
    try:
        # Validate date format
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
        # Check if the date has any available logs
        available_dates = get_available_log_dates()
        if date not in available_dates:
            raise HTTPException(
                status_code=404, 
                detail=f"No log files found for date {date}. Available dates: {', '.join(available_dates[:5])}"
            )
        
        files = get_log_files_for_date(date)
        return {"files": files}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting log files for date {date}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get log files")

@router.get("/content/{date}")
async def get_log_content(
    date: str,
    log_type: Optional[str] = Query(None, description="Log type: api, algosat, all"),
    limit: int = Query(1000, description="Maximum number of lines"),
    offset: int = Query(0, description="Number of lines to skip"),
    level: Optional[str] = Query(None, description="Filter by log level"),
    search: Optional[str] = Query(None, description="Search term"),
    current_user: dict = Depends(get_current_user)
):
    """Get log content for a specific date and type"""
    try:
        # Validate date format
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
        # Check if the date has any available logs
        available_dates = get_available_log_dates()
        if date not in available_dates:
            raise HTTPException(
                status_code=404, 
                detail=f"No log files found for date {date}. Available dates: {', '.join(available_dates[:5])}"
            )
        
        # Default to "all" if no log_type specified
        if log_type is None:
            log_type = "all"
        
        # Find the appropriate log file
        log_files = get_log_files_for_date(date)
        target_files = []
        
        if log_type == "all":
            target_files = log_files
        elif log_type == "rollover":
            target_files = [f for f in log_files if f.type == "rollover"]
        else:
            target_files = [f for f in log_files if f.type == log_type or (f.type == "rollover" and log_type in f.name)]
        
        if not target_files:
            available_types = list(set(f.type for f in log_files))
            raise HTTPException(
                status_code=404, 
                detail=f"No {log_type} log files found for {date}. Available types: {', '.join(available_types)}"
            )
        
        # Read from the main log file (and rollover files if needed)
        all_entries = []
        
        for log_file in sorted(target_files, key=lambda x: x.name):
            try:
                # Verify file still exists before trying to open
                log_path = Path(log_file.path)
                if not log_path.exists():
                    logger.warning(f"Log file {log_file.path} no longer exists, skipping")
                    continue
                    
                async with aiofiles.open(log_file.path, 'r') as f:
                    async for line in f:
                        entry = parse_log_line(line)
                        if entry:
                            # Apply filters
                            if level and entry.level != level.upper():
                                continue
                            if search and search.lower() not in entry.message.lower():
                                continue
                            all_entries.append(entry)
            except (IOError, OSError) as file_error:
                logger.error(f"Error reading log file {log_file.path}: {file_error}")
                # Continue with other files instead of failing completely
                continue
        
        # If no entries were read from any file, return appropriate error
        if not all_entries and target_files:
            raise HTTPException(
                status_code=500, 
                detail=f"Unable to read any log files for {date}. Files may be corrupted or inaccessible."
            )
        
        # Sort by timestamp (newest first)
        all_entries.sort(key=lambda x: x.timestamp, reverse=True)
        
        # Apply pagination
        total_count = len(all_entries)
        paginated_entries = all_entries[offset:offset + limit]
        
        return {
            "entries": paginated_entries,
            "total_count": total_count,
            "has_more": offset + limit < total_count,
            "date": date,
            "log_type": log_type
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    except Exception as e:
        logger.error(f"Error getting log content for {date}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get log content")

@router.post("/stream/session")
async def create_log_stream_session(
    log_type: Optional[str] = Query(None, description="Log type: api, algosat, all"),
    level: Optional[str] = Query(None, description="Filter by log level"),
    current_user: dict = Depends(get_current_user)
):
    """Create a temporary streaming session for real-time logs"""
    try:
        # Default to "all" if no log_type specified
        if log_type is None:
            log_type = "all"
            
        user_id = current_user.get("sub") or current_user.get("username", "unknown")
        session_id = create_streaming_session(user_id, log_type, level)
        
        return {
            "session_id": session_id,
            "stream_url": f"/logs/stream/live?session_id={session_id}",
            "expires_in": 1800,  # 30 minutes in seconds
            "log_type": log_type,
            "level": level
        }
    except Exception as e:
        logger.error(f"Error creating streaming session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create streaming session")

@router.get("/stream/live")
async def stream_live_logs(
    session_id: str = Query(..., description="Streaming session ID"),
):
    """Stream live logs in real-time using session-based authentication"""
    
    # Validate the streaming session
    session = validate_streaming_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired streaming session")
    
    log_type = session["log_type"]
    level = session["level"]
    user_id = session["user_id"]
    
    logger.info(f"Starting live log stream for user {user_id}, type: {log_type}, level: {level}")
    
    async def log_generator() -> AsyncGenerator[str, None]:
        # Get the current log files to monitor
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Check both new date-based directory structure and legacy flat structure
        date_dir = LOGS_BASE_DIR / today
        
        log_files_to_monitor = []
        if log_type == "all":
            # Monitor all main application logs only
            if date_dir.exists():
                api_log = date_dir / f"api-{today}.log"
                algosat_log = date_dir / f"algosat-{today}.log"
                broker_log = date_dir / f"broker_monitor-{today}.log"
                log_files_to_monitor = [api_log, algosat_log, broker_log]
            else:
                # Fallback to legacy flat structure
                api_log = LOGS_BASE_DIR / f"api-{today}.log"
                algosat_log = LOGS_BASE_DIR / f"algosat-{today}.log"
                broker_log = LOGS_BASE_DIR / f"broker_monitor-{today}.log"
                log_files_to_monitor = [api_log, algosat_log, broker_log]
        elif log_type == "api":
            if date_dir.exists():
                log_files_to_monitor = [date_dir / f"api-{today}.log"]
            else:
                log_files_to_monitor = [LOGS_BASE_DIR / f"api-{today}.log"]
        elif log_type == "algosat":
            if date_dir.exists():
                log_files_to_monitor = [date_dir / f"algosat-{today}.log"]
            else:
                log_files_to_monitor = [LOGS_BASE_DIR / f"algosat-{today}.log"]
        elif log_type == "broker-monitor":
            if date_dir.exists():
                log_files_to_monitor = [date_dir / f"broker_monitor-{today}.log"]
            else:
                log_files_to_monitor = [LOGS_BASE_DIR / f"broker_monitor-{today}.log"]
        else:
            # Default case - should not normally reach here
            log_files_to_monitor = []
        
        # Keep track of file positions
        file_positions = {str(log_file): 0 for log_file in log_files_to_monitor}
        
        # Debug logging
        logger.info(f"Live stream monitoring files: {[str(f) for f in log_files_to_monitor]}")
        for log_file in log_files_to_monitor:
            exists = log_file.exists()
            logger.info(f"File {log_file}: exists={exists}")
            if exists:
                try:
                    size = log_file.stat().st_size
                    logger.info(f"File {log_file}: size={size} bytes")
                except Exception as e:
                    logger.error(f"Error getting size for {log_file}: {e}")
        
        try:
            while True:
                # Check if session is still valid
                current_session = validate_streaming_session(session_id)
                if not current_session:
                    yield f"data: {json.dumps({'error': 'Session expired'})}\n\n"
                    return
                
                # Check each log file for new content
                for log_file_path in log_files_to_monitor:
                    if log_file_path.exists():
                        async with aiofiles.open(log_file_path, 'r') as f:
                            await f.seek(file_positions[str(log_file_path)])
                            
                            async for line in f:
                                entry = parse_log_line(line)
                                if entry:
                                    # Apply level filter
                                    if level and entry.level != level.upper():
                                        continue
                                    
                                    # Create stream response
                                    response = LogStreamResponse(
                                        entry=entry,
                                        file=log_file_path.name,
                                        position=await f.tell()
                                    )
                                    
                                    yield f"data: {response.json()}\n\n"
                            
                            file_positions[str(log_file_path)] = await f.tell()
                
                # Wait before checking for new lines
                await asyncio.sleep(0.5)
                
        except Exception as e:
            logger.error(f"Error in log stream for session {session_id}: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            # Clean up session when stream ends
            if session_id in STREAMING_SESSIONS:
                del STREAMING_SESSIONS[session_id]
                logger.info(f"Cleaned up streaming session {session_id}")
    
    return StreamingResponse(
        log_generator(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
        }
    )

@router.post("/cleanup")
async def cleanup_logs(
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """Trigger cleanup of old log files"""
    try:
        deleted_count = await cleanup_old_logs()
        return {
            "message": f"Log cleanup completed. Deleted {deleted_count} old files.",
            "deleted_count": deleted_count
        }
    except Exception as e:
        logger.error(f"Error during log cleanup: {e}")
        raise HTTPException(status_code=500, detail="Failed to cleanup logs")

@router.get("/stats")
async def get_log_stats(
    current_user: dict = Depends(get_current_user)
):
    """Get log statistics and metrics"""
    try:
        available_dates = get_available_log_dates()
        stats = {
            "total_dates": len(available_dates),
            "date_range": {
                "start": available_dates[-1] if available_dates else None,
                "end": available_dates[0] if available_dates else None
            },
            "retention_days": MAX_LOG_RETENTION_DAYS,
            "log_types": list(LOG_PATTERNS.keys()),
            "files_by_type": {},
            "total_size": 0
        }
        
        for date in available_dates:
            files = get_log_files_for_date(date)
            for file in files:
                if file.type not in stats["files_by_type"]:
                    stats["files_by_type"][file.type] = {"count": 0, "size": 0}
                stats["files_by_type"][file.type]["count"] += 1
                stats["files_by_type"][file.type]["size"] += file.size
                stats["total_size"] += file.size
        
        return stats
    except Exception as e:
        logger.error(f"Error getting log stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get log statistics")

@router.get("/download")
async def download_logs(
    date: str = Query(..., description="Log date in YYYY-MM-DD format"),
    log_type: Optional[str] = Query(None, description="Log type filter (api, algosat, rollover)"),
    current_user: dict = Depends(get_current_user)
):
    """Download log files for a specific date as a text file"""
    try:
        if date not in get_available_log_dates():
            raise HTTPException(status_code=404, detail=f"No logs found for date {date}")
        
        log_files = get_log_files_for_date(date)
        
        # Filter by log type if specified
        if log_type:
            log_files = [f for f in log_files if f.type == log_type]
        
        if not log_files:
            raise HTTPException(status_code=404, detail=f"No logs found for date {date}" + (f" and type {log_type}" if log_type else ""))
        
        # Generate combined log content
        def generate_log_content():
            for log_file in sorted(log_files, key=lambda x: x.modified):
                yield f"\n{'='*80}\n"
                yield f"LOG FILE: {log_file.name}\n"
                yield f"TYPE: {log_file.type}\n"
                yield f"SIZE: {log_file.size} bytes\n"
                yield f"MODIFIED: {log_file.modified}\n"
                yield f"{'='*80}\n\n"
                
                try:
                    with open(log_file.path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            yield line
                except Exception as e:
                    yield f"ERROR READING FILE: {str(e)}\n"
                
                yield f"\n{'='*80}\n"
                yield f"END OF {log_file.name}\n"
                yield f"{'='*80}\n\n"
        
        filename = f"algosat-logs-{date}" + (f"-{log_type}" if log_type else "") + ".txt"
        
        return StreamingResponse(
            generate_log_content(),
            media_type="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading logs for date {date}: {e}")
        raise HTTPException(status_code=500, detail="Failed to download logs")
