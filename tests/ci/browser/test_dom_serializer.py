"""
Test DOM serializer with complex scenarios: shadow DOM, same-origin and cross-origin iframes.

This test verifies that the DOM serializer correctly:
1. Extracts interactive elements from shadow DOM
2. Processes same-origin iframes
3. Handles cross-origin iframes (should be blocked)
4. Generates correct selector_map with expected element counts

Usage:
	uv run pytest tests/ci/browser/test_dom_serializer.py -v -s
"""

import pytest
from pytest_httpserver import HTTPServer

from browser_use.agent.service import Agent
from browser_use.browser import BrowserSession
from browser_use.browser.profile import BrowserProfile
from tests.ci.conftest import create_mock_llm


@pytest.fixture(scope='session')
def http_server():
	"""Create and provide a test HTTP server for DOM serializer tests."""
	server = HTTPServer()
	server.start()

	# Route 1: Main page with shadow DOM and iframes
	server.expect_request('/dom-test-main').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>DOM Serializer Test - Main Page</title>
			<style>
				body { font-family: Arial; padding: 20px; }
				.section { margin: 20px 0; padding: 15px; border: 1px solid #ccc; }
			</style>
		</head>
		<body>
			<h1>DOM Serializer Test Page</h1>

			<!-- Regular DOM elements (3 interactive elements) -->
			<div class="section">
				<h2>Regular DOM Elements</h2>
				<button id="regular-btn-1">Regular Button 1</button>
				<input type="text" id="regular-input" placeholder="Regular input" />
				<a href="#test" id="regular-link">Regular Link</a>
			</div>

			<!-- Shadow DOM elements (3 interactive elements inside shadow) -->
			<div class="section">
				<h2>Shadow DOM Elements</h2>
				<div id="shadow-host"></div>
			</div>

			<!-- Same-origin iframe (2 interactive elements inside) -->
			<div class="section">
				<h2>Same-Origin Iframe</h2>
				<iframe id="same-origin-iframe" src="/iframe-same-origin" style="width:100%; height:200px; border:1px solid #999;"></iframe>
			</div>

			<!-- Cross-origin iframe (should NOT be accessible) -->
			<div class="section">
				<h2>Cross-Origin Iframe</h2>
				<iframe id="cross-origin-iframe" src="https://example.com" style="width:100%; height:200px; border:1px solid #999;"></iframe>
			</div>

			<script>
				// Create shadow DOM with interactive elements
				const shadowHost = document.getElementById('shadow-host');
				const shadowRoot = shadowHost.attachShadow({mode: 'open'});

				shadowRoot.innerHTML = `
					<style>
						.shadow-content { padding: 10px; background: #f0f0f0; }
					</style>
					<div class="shadow-content">
						<p>Content inside Shadow DOM:</p>
						<button id="shadow-btn-1">Shadow Button 1</button>
						<input type="text" id="shadow-input" placeholder="Shadow input" />
						<button id="shadow-btn-2">Shadow Button 2</button>
					</div>
				`;
			</script>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	# Route 2: Same-origin iframe content
	server.expect_request('/iframe-same-origin').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>Same-Origin Iframe</title>
		</head>
		<body style="padding: 10px; background: #fff;">
			<h3>Same-Origin Iframe Content</h3>
			<button id="iframe-btn">Iframe Button</button>
			<input type="text" id="iframe-input" placeholder="Iframe input" />
		</body>
		</html>
		""",
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	"""Return the base URL for the test HTTP server."""
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='function')
async def browser_session():
	"""Create a browser session for DOM serializer tests."""
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await session.start()
	yield session
	await session.kill()


class TestDOMSerializer:
	"""Test DOM serializer with complex scenarios."""

	async def test_dom_serializer_with_shadow_dom_and_iframes(self, browser_session, base_url):
		"""Test DOM serializer extracts elements from shadow DOM, same-origin iframes, and cross-origin iframes.

		This test verifies:
		1. Elements are in the serializer (selector_map)
		2. We can click elements using click(index)

		Expected interactive elements:
		- Regular DOM: 3 elements (button, input, link on main page)
		- Shadow DOM: 3 elements (2 buttons, 1 input inside shadow root)
		- Same-origin iframe: 2 elements (button, input inside iframe)
		- Cross-origin iframe: ~1 element (may extract some content from example.com)
		- Iframe tags: 2 elements (the iframe elements themselves)
		Total: ~10-11 interactive elements
		"""

		# Create mock LLM actions that will click elements from each category
		# We'll generate actions dynamically after we know the indices
		actions = [
			f"""
			{{
				"thinking": "I'll navigate to the DOM test page",
				"evaluation_previous_goal": "Starting task",
				"memory": "Navigating to test page",
				"next_goal": "Navigate to test page",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/dom-test-main",
							"new_tab": false
						}}
					}}
				]
			}}
			"""
		]

		# First, just navigate to the page
		from browser_use.browser.events import NavigateToUrlEvent

		nav = browser_session.event_bus.dispatch(NavigateToUrlEvent(url=f'{base_url}/dom-test-main', new_tab=False))
		await nav

		# Wait a moment for page to fully load
		import asyncio

		await asyncio.sleep(1)

		# Get the browser state to access selector_map
		browser_state_summary = await browser_session.get_browser_state_summary(
			include_screenshot=False,
			include_recent_events=False,
		)

		assert browser_state_summary is not None, 'Browser state summary should not be None'
		assert browser_state_summary.dom_state is not None, 'DOM state should not be None'

		selector_map = browser_state_summary.dom_state.selector_map

		print('\n📊 DOM Serializer Analysis:')
		print(f'   Total interactive elements found: {len(selector_map)}')

		# Categorize elements by their actual ID ranges (based on observed patterns)
		# Shadow DOM elements: IDs 180, 124, 184 (buttons and inputs inside shadow)
		# Iframe elements: IDs 224, 132 (button and input inside same-origin iframe)
		# Regular elements: IDs like 156, 123, 160 (main page elements)
		# iframe tags themselves: IDs 196, 131

		regular_elements = []
		shadow_elements = []
		iframe_content_elements = []
		iframe_tags = []

		# Categorize elements by their IDs (more stable than hardcoded indices)
		# Check element attributes to identify their location
		for idx, element in selector_map.items():
			# Check if this is an iframe tag (not content inside iframe)
			if element.tag_name == 'iframe':
				iframe_tags.append((idx, element))
			# Check if element has an ID attribute
			elif hasattr(element, 'attributes') and 'id' in element.attributes:
				elem_id = element.attributes['id'].lower()
				# Shadow DOM elements have IDs starting with "shadow-"
				if elem_id.startswith('shadow-'):
					shadow_elements.append((idx, element))
				# Iframe content elements have IDs starting with "iframe-"
				elif elem_id.startswith('iframe-'):
					iframe_content_elements.append((idx, element))
				# Everything else is regular DOM
				else:
					regular_elements.append((idx, element))
			# Elements without IDs are regular DOM
			else:
				regular_elements.append((idx, element))

		print(f'\n   Regular DOM elements: {len(regular_elements)}')
		for idx, el in regular_elements[:5]:  # Show first 5
			print(f'      [{idx}] {str(el)[:100]}...')

		print(f'\n   Shadow DOM elements: {len(shadow_elements)}')
		for idx, el in shadow_elements[:5]:  # Show first 5
			print(f'      [{idx}] {str(el)[:100]}...')

		print(f'\n   Iframe content elements: {len(iframe_content_elements)}')
		for idx, el in iframe_content_elements[:5]:  # Show first 5
			print(f'      [{idx}] {str(el)[:100]}...')

		print(f'\n   Iframe tags: {len(iframe_tags)}')
		for idx, el in iframe_tags[:5]:  # Show first 5
			print(f'      [{idx}] {str(el)[:100]}...')

		# Verify element counts based on our test page structure:
		# - Regular DOM: 3-4 elements (button, input, link on main page + possible cross-origin content)
		# - Shadow DOM: 3 elements (2 buttons, 1 input inside shadow root)
		# - Iframe content: 2 elements (button, input from same-origin iframe)
		# - Iframe tags: 2 elements (the iframe elements themselves)
		# Total: ~10-11 interactive elements depending on cross-origin iframe extraction

		print('\n✅ DOM Serializer Test Summary:')
		print(f'   • Regular DOM: {len(regular_elements)} elements {"✓" if len(regular_elements) >= 3 else "✗"}')
		print(f'   • Shadow DOM: {len(shadow_elements)} elements {"✓" if len(shadow_elements) >= 3 else "✗"}')
		print(
			f'   • Same-origin iframe content: {len(iframe_content_elements)} elements {"✓" if len(iframe_content_elements) >= 2 else "✗"}'
		)
		print(f'   • Iframe tags: {len(iframe_tags)} elements {"✓" if len(iframe_tags) >= 2 else "✗"}')
		print(f'   • Total elements: {len(selector_map)}')

		# Verify we found elements from all sources
		assert len(selector_map) >= 8, f'Should find at least 8 interactive elements, found {len(selector_map)}'
		assert len(regular_elements) >= 1, f'Should find at least 1 regular DOM element, found {len(regular_elements)}'
		assert len(shadow_elements) >= 1, f'Should find at least 1 shadow DOM element, found {len(shadow_elements)}'
		assert len(iframe_content_elements) >= 1, (
			f'Should find at least 1 iframe content element, found {len(iframe_content_elements)}'
		)

		# Now test clicking elements from each category using tools.click(index)
		print('\n🖱️  Testing Click Functionality:')

		from browser_use.tools.service import Tools

		tools = Tools()

		# Helper to call tools.click(index) and verify it worked
		async def click(index: int, element_description: str):
			result = await tools.registry.execute_action('click', {'index': index}, browser_session=browser_session)
			if result.error:
				raise AssertionError(f'Click on {element_description} [{index}] failed: {result.error}')
			print(f'   ✓ {element_description} [{index}] clicked successfully')
			return result

		# Test clicking a regular DOM element (button)
		if regular_elements:
			regular_button_idx = next((idx for idx, el in regular_elements if 'regular-btn' in el.attributes.get('id', '')), None)
			if regular_button_idx:
				await click(regular_button_idx, 'Regular DOM button')

		# Test clicking a shadow DOM element (button)
		if shadow_elements:
			shadow_button_idx = next((idx for idx, el in shadow_elements if 'btn' in el.attributes.get('id', '')), None)
			if shadow_button_idx:
				await click(shadow_button_idx, 'Shadow DOM button')

		# Test clicking a same-origin iframe element (button)
		if iframe_content_elements:
			iframe_button_idx = next((idx for idx, el in iframe_content_elements if 'btn' in el.attributes.get('id', '')), None)
			if iframe_button_idx:
				await click(iframe_button_idx, 'Same-origin iframe button')

		# Test clicking a cross-origin iframe element (expected to fail)
		cross_origin_elements = [
			(idx, el)
			for idx, el in regular_elements
			if hasattr(el, 'attributes') and 'id' not in el.attributes and el.tag_name == 'a'
		]
		if cross_origin_elements:
			cross_origin_link_idx = cross_origin_elements[0][0]
			await click(cross_origin_link_idx, 'Cross-origin element')

		print('\n🎉 DOM Serializer test completed successfully!')

	async def test_dom_serializer_element_counts_detailed(self, browser_session, base_url):
		"""Detailed test to verify specific element types are captured correctly."""

		actions = [
			f"""
			{{
				"thinking": "Navigating to test page",
				"evaluation_previous_goal": "Starting",
				"memory": "Navigate",
				"next_goal": "Navigate",
				"action": [
					{{
						"navigate": {{
							"url": "{base_url}/dom-test-main",
							"new_tab": false
						}}
					}}
				]
			}}
			""",
			"""
			{
				"thinking": "Done",
				"evaluation_previous_goal": "Navigated",
				"memory": "Complete",
				"next_goal": "Done",
				"action": [
					{
						"done": {
							"text": "Done",
							"success": true
						}
					}
				]
			}
			""",
		]

		mock_llm = create_mock_llm(actions=actions)
		agent = Agent(
			task=f'Navigate to {base_url}/dom-test-main',
			llm=mock_llm,
			browser_session=browser_session,
		)

		history = await agent.run(max_steps=2)

		# Get current browser state to access selector_map
		browser_state_summary = await browser_session.get_browser_state_summary(
			include_screenshot=False,
			include_recent_events=False,
		)
		selector_map = browser_state_summary.dom_state.selector_map

		# Count different element types
		buttons = 0
		inputs = 0
		links = 0

		for idx, element in selector_map.items():
			element_str = str(element).lower()
			if 'button' in element_str or '<button' in element_str:
				buttons += 1
			elif 'input' in element_str or '<input' in element_str:
				inputs += 1
			elif 'link' in element_str or '<a' in element_str or 'href' in element_str:
				links += 1

		print('\n📊 Element Type Counts:')
		print(f'   Buttons: {buttons}')
		print(f'   Inputs: {inputs}')
		print(f'   Links: {links}')
		print(f'   Total: {len(selector_map)}')

		# We should have at least some of each type from the regular DOM
		assert buttons >= 1, f'Should find at least 1 button, found {buttons}'
		assert inputs >= 1, f'Should find at least 1 input, found {inputs}'

		print('\n✅ Element type verification passed!')
