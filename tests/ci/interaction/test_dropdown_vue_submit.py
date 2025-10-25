"""
Test Vue.js dropdown selection with form submission.

This test verifies that dropdown selections persist through Vue's v-model
and are correctly submitted with the form. This was the bug reported in issue #3415.
"""



class TestVueDropdownSubmit:
	"""Test Vue.js dropdown with v-model and form submission."""

	async def test_vue_dropdown_selection_with_submit(self, tools, browser_session, httpserver):
		"""Test that Vue.js dropdown selections persist and submit correctly."""
		# Simple Vue.js page with dropdown + submit button
		html_content = """
		<!DOCTYPE html>
		<html>
		<head>
			<meta charset="UTF-8">
			<title>Vue Dropdown Test</title>
			<script src="https://cdn.jsdelivr.net/npm/vue@3/dist/vue.global.js"></script>
			<style>
				body { font-family: Arial, sans-serif; padding: 20px; }
				.container { max-width: 400px; margin: 0 auto; }
				label { display: block; margin: 10px 0 5px; font-weight: bold; }
				select { width: 100%; padding: 8px; font-size: 16px; }
				button { margin-top: 20px; padding: 10px 20px; background: #4CAF50; color: white; border: none; cursor: pointer; font-size: 16px; }
				button:hover { background: #45a049; }
				#result { margin-top: 20px; padding: 10px; background: #f0f0f0; border-radius: 4px; }
			</style>
		</head>
		<body>
			<div id="app" class="container">
				<h2>Vue.js Dropdown Form</h2>

				<form @submit.prevent="submitForm">
					<label for="pay-frequency">Pay Frequency *</label>
					<select id="pay-frequency" v-model="payFrequency" required>
						<option value="">Select Frequency</option>
						<option value="peryear">per year</option>
						<option value="perhour">per hour</option>
					</select>

					<label for="hire-type">Hire Type *</label>
					<select id="hire-type" v-model="hireType" required>
						<option value="">Select Type</option>
						<option value="w-2">W-2</option>
						<option value="1099">1099</option>
						<option value="k-1">K-1</option>
						<option value="test">Test</option>
					</select>

					<button type="submit">Submit</button>
				</form>

				<div id="result" v-if="submitted">
					<h3>Form Submitted Successfully!</h3>
					<p><strong>Pay Frequency:</strong> {{ submittedData.payFrequency }}</p>
					<p><strong>Hire Type:</strong> {{ submittedData.hireType }}</p>
				</div>
			</div>

			<script>
				const { createApp } = Vue;

				createApp({
					data() {
						return {
							payFrequency: '',
							hireType: '',
							submitted: false,
							submittedData: {}
						};
					},
					methods: {
						submitForm() {
							// This validates that Vue's v-model properly captured the selections
							this.submittedData = {
								payFrequency: this.payFrequency,
								hireType: this.hireType
							};
							this.submitted = true;

							// Also send to server for validation
							fetch('/submit', {
								method: 'POST',
								headers: { 'Content-Type': 'application/json' },
								body: JSON.stringify(this.submittedData)
							});
						}
					}
				}).mount('#app');
			</script>
		</body>
		</html>
		"""

		httpserver.expect_request('/vue-dropdown').respond_with_data(html_content, content_type='text/html')

		# Server-side validation endpoint
		received_data = []

		def handle_submit(request):
			import json

			data = json.loads(request.get_data(as_text=True))
			received_data.append(data)
			return json.dumps({'success': True, 'received': data})

		httpserver.expect_request('/submit', method='POST').respond_with_handler(handle_submit)

		# Navigate to the Vue.js form
		from browser_use.agent.views import ActionModel
		from browser_use.tools.views import GoToUrlAction

		base_url = httpserver.url_for('/')

		class NavigateActionModel(ActionModel):
			navigate: GoToUrlAction | None = None

		action = NavigateActionModel(navigate=GoToUrlAction(url=f'{base_url}vue-dropdown', new_tab=False))
		result = await tools.act(action, browser_session)
		assert result.error is None

		# Wait for Vue to initialize
		import asyncio

		await asyncio.sleep(0.5)

		# Get browser state to find dropdown elements
		await browser_session.get_browser_state_summary()
		selector_map = await browser_session.get_selector_map()

		# Find the pay frequency dropdown (should be index 3 or similar)
		pay_freq_element = None
		hire_type_element = None

		for idx, element in selector_map.items():
			if element.attributes.get('id') == 'pay-frequency':
				pay_freq_element = idx
			elif element.attributes.get('id') == 'hire-type':
				hire_type_element = idx

		assert pay_freq_element is not None, 'Could not find pay-frequency dropdown'
		assert hire_type_element is not None, 'Could not find hire-type dropdown'

		# Create a model for the standard select_dropdown action
		class SelectDropdownModel(ActionModel):
			select_dropdown: dict

		# Select "per hour" from pay frequency dropdown
		result = await tools.act(
			SelectDropdownModel(select_dropdown={'index': pay_freq_element, 'text': 'per hour'}),
			browser_session,
		)
		assert result.error is None, f'Failed to select pay frequency: {result.error}'

		# Select "1099" from hire type dropdown
		result = await tools.act(
			SelectDropdownModel(select_dropdown={'index': hire_type_element, 'text': '1099'}),
			browser_session,
		)
		assert result.error is None, f'Failed to select hire type: {result.error}'

		# Find and click the submit button
		await browser_session.get_browser_state_summary()
		selector_map = await browser_session.get_selector_map()
		submit_button = None

		for idx, element in selector_map.items():
			if element.tag_name == 'button' and element.attributes.get('type') == 'submit':
				submit_button = idx
				break

		assert submit_button is not None, 'Could not find submit button'

		# Create a model for the standard click action
		class ClickModel(ActionModel):
			click: dict

		result = await tools.act(
			ClickModel(click={'index': submit_button}),
			browser_session,
		)
		assert result.error is None, f'Failed to click submit: {result.error}'

		# Wait for submission
		await asyncio.sleep(1)

		# Verify the form was submitted with correct values
		assert len(received_data) > 0, 'No data was submitted to server'
		submitted = received_data[0]

		# THIS IS THE KEY TEST: Vue's v-model should have captured both selections
		assert submitted['payFrequency'] == 'perhour', f"Expected 'perhour', got {submitted['payFrequency']}"
		assert submitted['hireType'] == '1099', f"Expected '1099', got {submitted['hireType']}"

		# Also verify the result is displayed on the page using CDP
		cdp_session = await browser_session.get_or_create_cdp_session()
		page_text_result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'document.body.textContent', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		page_text = page_text_result.get('result', {}).get('value', '').lower()

		assert 'form submitted successfully' in page_text, 'Success message not found'
		assert 'per hour' in page_text, 'Pay frequency not displayed in result'
		assert '1099' in page_text, 'Hire type not displayed in result'
