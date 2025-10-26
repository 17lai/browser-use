"""Event-driven CDP session management.

Sessions are managed by listening to
Target.attachedToTarget and Target.detachedFromTarget events, ensuring the
session pool always reflects the current browser state.
"""

import asyncio
from typing import TYPE_CHECKING, Dict, Set

from cdp_use.cdp.target import AttachedToTargetEvent, DetachedFromTargetEvent, SessionID, TargetID

if TYPE_CHECKING:
	from browser_use.browser.session import BrowserSession, CDPSession


class SessionManager:
	"""Manages CDP sessions with event-driven synchronization.

	Key differences from manual caching:
	- Sessions are added/removed via CDP events, not manual calls
	- Multiple sessions can attach to the same target
	- Targets are only removed when ALL sessions detach
	- No stale sessions - pool always reflects browser reality
	"""

	def __init__(self, browser_session: 'BrowserSession'):
		self.browser_session = browser_session
		self.logger = browser_session.logger

		# Target -> Set of sessions attached to it
		self._target_sessions: Dict[TargetID, Set[SessionID]] = {}

		# Session -> Target mapping (for reverse lookup)
		self._session_to_target: Dict[SessionID, TargetID] = {}

		# Lock for thread-safe access
		self._lock = asyncio.Lock()

	async def start_monitoring(self) -> None:
		"""Start monitoring Target attach/detach events.

		This registers CDP event handlers that keep the session pool synchronized.
		"""
		if not self.browser_session._cdp_client_root:
			raise RuntimeError('CDP client not initialized')

		# Capture cdp_client_root in closure to avoid type errors
		cdp_client = self.browser_session._cdp_client_root

		# Register synchronous event handlers (CDP requirement)
		def on_attached(event: AttachedToTargetEvent, session_id: SessionID | None = None):
			event_session_id = event['sessionId']
			target_type = event['targetInfo'].get('type', 'unknown')

			# Enable auto-attach for this session's children
			# Note: For short-lived targets (workers, temp iframes), this may fail with -32001
			# This is EXPECTED - the session_id is valid when event fires, but may detach
			# before our async task executes. We catch and ignore these errors.
			async def _enable_auto_attach():
				try:
					await cdp_client.send.Target.setAutoAttach(
						params={'autoAttach': True, 'waitForDebuggerOnStart': False, 'flatten': True}, session_id=event_session_id
					)
					self.logger.debug(f'[SessionManager] Auto-attach enabled for {target_type} session {event_session_id[:8]}...')
				except Exception as e:
					# Expected for workers/temp iframes that attach/detach rapidly
					# The session_id is valid in the event, but gone by the time task executes
					error_str = str(e)
					if '-32001' in error_str or 'Session with given id not found' in error_str:
						self.logger.debug(
							f'[SessionManager] setAutoAttach skipped - {target_type} session {event_session_id[:8]}... '
							f'already detached (normal for short-lived targets)'
						)
					else:
						self.logger.debug(f'[SessionManager] setAutoAttach failed: {e}')

			# Schedule auto-attach and pool management
			asyncio.create_task(_enable_auto_attach())
			asyncio.create_task(self._handle_target_attached(event))

		def on_detached(event: DetachedFromTargetEvent, session_id: SessionID | None = None):
			asyncio.create_task(self._handle_target_detached(event))

		self.browser_session._cdp_client_root.register.Target.attachedToTarget(on_attached)
		self.browser_session._cdp_client_root.register.Target.detachedFromTarget(on_detached)

		self.logger.info('[SessionManager] Event monitoring started')

	async def _handle_target_attached(self, event: AttachedToTargetEvent) -> None:
		"""Handle Target.attachedToTarget event.

		Called automatically by Chrome when a new target/session is created.
		This is the ONLY place where sessions should be added to the pool.
		"""
		target_id = event['targetInfo']['targetId']
		session_id = event['sessionId']
		target_type = event['targetInfo']['type']
		waiting_for_debugger = event.get('waitingForDebugger', False)

		self.logger.debug(
			f'[SessionManager] Target attached: {target_id[:8]}... (session={session_id[:8]}..., '
			f'type={target_type}, waitingForDebugger={waiting_for_debugger})'
		)

		async with self._lock:
			# Track this session for the target
			if target_id not in self._target_sessions:
				self._target_sessions[target_id] = set()

			self._target_sessions[target_id].add(session_id)
			self._session_to_target[session_id] = target_id

			# Create CDPSession wrapper and add to pool
			if target_id not in self.browser_session._cdp_session_pool:
				# Create session wrapper (uses shared WebSocket, just tracks session_id)
				from browser_use.browser.session import CDPSession

				assert self.browser_session._cdp_client_root is not None, 'Root CDP client required'

				cdp_session = CDPSession(
					cdp_client=self.browser_session._cdp_client_root,
					target_id=target_id,
					session_id=session_id,
					title=event['targetInfo'].get('title', 'Unknown title'),
					url=event['targetInfo'].get('url', 'about:blank'),
				)

				self.browser_session._cdp_session_pool[target_id] = cdp_session

				self.logger.debug(
					f'[SessionManager] Created session for target {target_id[:8]}... '
					f'(pool size: {len(self.browser_session._cdp_session_pool)})'
				)
			else:
				# Update existing session with new session_id
				existing = self.browser_session._cdp_session_pool[target_id]
				existing.session_id = session_id
				existing.title = event['targetInfo'].get('title', existing.title)
				existing.url = event['targetInfo'].get('url', existing.url)

		# Resume execution if waiting for debugger
		if waiting_for_debugger:
			try:
				assert self.browser_session._cdp_client_root is not None
				await self.browser_session._cdp_client_root.send.Runtime.runIfWaitingForDebugger(session_id=session_id)
				self.logger.debug(f'[SessionManager] Resumed execution for session {session_id[:8]}...')
			except Exception as e:
				self.logger.warning(f'[SessionManager] Failed to resume execution: {e}')

	async def _handle_target_detached(self, event: DetachedFromTargetEvent) -> None:
		"""Handle Target.detachedFromTarget event.

		Called automatically by Chrome when a target/session is destroyed.
		This is the ONLY place where sessions should be removed from the pool.
		"""
		session_id = event['sessionId']
		target_id = event.get('targetId')  # May be empty

		# If targetId not in event, look it up via session mapping
		if not target_id:
			async with self._lock:
				target_id = self._session_to_target.get(session_id)

		if not target_id:
			self.logger.warning(f'[SessionManager] Session detached but target unknown (session={session_id[:8]}...)')
			return

		async with self._lock:
			# Remove this session from target's session set
			if target_id in self._target_sessions:
				self._target_sessions[target_id].discard(session_id)

				remaining_sessions = len(self._target_sessions[target_id])

				self.logger.debug(
					f'[SessionManager] Session detached: target={target_id[:8]}... '
					f'session={session_id[:8]}... (remaining={remaining_sessions})'
				)

				# Only remove target when NO sessions remain
				if remaining_sessions == 0:
					self.logger.info(f'[SessionManager] No sessions remain for target {target_id[:8]}..., removing from pool')

					# Remove from pool
					if target_id in self.browser_session._cdp_session_pool:
						stale_session = self.browser_session._cdp_session_pool.pop(target_id)
						# Don't disconnect - we're using shared WebSocket
						self.logger.debug(
							f'[SessionManager] Removed target {target_id[:8]}... from pool '
							f'(pool size: {len(self.browser_session._cdp_session_pool)})'
						)

					# Clean up tracking
					del self._target_sessions[target_id]

			# Remove from reverse mapping
			if session_id in self._session_to_target:
				del self._session_to_target[session_id]

	async def get_session_for_target(self, target_id: TargetID) -> 'CDPSession | None':
		"""Get the current valid session for a target.

		Returns None if no session exists (target detached).
		"""
		async with self._lock:
			return self.browser_session._cdp_session_pool.get(target_id)

	async def validate_session(self, target_id: TargetID) -> bool:
		"""Check if a target still has active sessions.

		Returns True if target is valid, False if it should be removed.
		"""
		async with self._lock:
			if target_id not in self._target_sessions:
				return False

			return len(self._target_sessions[target_id]) > 0

	async def clear(self) -> None:
		"""Clear all session tracking (for cleanup)."""
		async with self._lock:
			self._target_sessions.clear()
			self._session_to_target.clear()

		self.logger.info('[SessionManager] Cleared all session tracking')
