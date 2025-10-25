"""
Test React dropdown selection with form submission.

This test verifies that dropdown selections work correctly with React's
controlled components and state management.
"""



class TestReactDropdownSubmit:
	"""Test React dropdown with controlled components and form submission."""

	async def test_react_dropdown_selection_with_submit(self, tools, browser_session, httpserver):
		"""Test that React dropdown selections persist and submit correctly."""
		# Simple React page with dropdown + submit button
		html_content = """
		<!DOCTYPE html>
		<html>
		<head>
			<meta charset="UTF-8">
			<title>React Dropdown Test</title>
			<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
			<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
			<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
			<style>
				body { font-family: Arial, sans-serif; padding: 20px; }
				.container { max-width: 400px; margin: 0 auto; }
				label { display: block; margin: 10px 0 5px; font-weight: bold; }
				select { width: 100%; padding: 8px; font-size: 16px; }
				button { margin-top: 20px; padding: 10px 20px; background: #61dafb; color: #282c34; border: none; cursor: pointer; font-size: 16px; font-weight: bold; }
				button:hover { background: #4fa8c5; }
				.result { margin-top: 20px; padding: 10px; background: #f0f0f0; border-radius: 4px; }
			</style>
		</head>
		<body>
			<div id="root"></div>

			<script type="text/babel">
				const { useState } = React;

				function DropdownForm() {
					const [employmentStatus, setEmploymentStatus] = useState('fullTime');
					const [hireType, setHireType] = useState('');
					const [submitted, setSubmitted] = useState(false);
					const [submittedData, setSubmittedData] = useState({});

					const handleSubmit = (e) => {
						e.preventDefault();

						// This validates that React state properly captured the selections
						const data = {
							employmentStatus,
							hireType
						};

						setSubmittedData(data);
						setSubmitted(true);

						// Send to server for validation
						fetch('/submit', {
							method: 'POST',
							headers: { 'Content-Type': 'application/json' },
							body: JSON.stringify(data)
						});
					};

					return (
						<div className="container">
							<h2>React Dropdown Form</h2>

							<form onSubmit={handleSubmit}>
								<label htmlFor="employment-status">
									Employment Status *
								</label>
								<select
									id="employment-status"
									value={employmentStatus}
									onChange={(e) => setEmploymentStatus(e.target.value)}
									required
								>
									<option value="fullTime">Full Time</option>
									<option value="partTime">Part Time</option>
								</select>

								<label htmlFor="hire-type">
									Hire Type *
								</label>
								<select
									id="hire-type"
									value={hireType}
									onChange={(e) => setHireType(e.target.value)}
									required
								>
									<option value="">Select Type</option>
									<option value="w-2">W-2</option>
									<option value="1099">1099</option>
									<option value="k-1">K-1</option>
									<option value="test">Test</option>
								</select>

								<button type="submit">Submit</button>
							</form>

							{submitted && (
								<div className="result">
									<h3>Form Submitted Successfully!</h3>
									<p><strong>Employment Status:</strong> {submittedData.employmentStatus}</p>
									<p><strong>Hire Type:</strong> {submittedData.hireType}</p>
								</div>
							)}
						</div>
					);
				}

				const root = ReactDOM.createRoot(document.getElementById('root'));
				root.render(<DropdownForm />);
			</script>
		</body>
		</html>
		"""

		httpserver.expect_request('/react-dropdown').respond_with_data(html_content, content_type='text/html')

		# Server-side validation endpoint
		received_data = []

		def handle_submit(request):
			import json

			data = json.loads(request.get_data(as_text=True))
			received_data.append(data)
			return json.dumps({'success': True, 'received': data})

		httpserver.expect_request('/submit', method='POST').respond_with_handler(handle_submit)

		# Navigate to the React form
		from browser_use.agent.views import ActionModel
		from browser_use.tools.views import GoToUrlAction

		base_url = httpserver.url_for('/')

		class NavigateActionModel(ActionModel):
			navigate: GoToUrlAction | None = None

		action = NavigateActionModel(navigate=GoToUrlAction(url=f'{base_url}react-dropdown', new_tab=False))
		result = await tools.act(action, browser_session)
		assert result.error is None

		# Wait for React to initialize
		import asyncio

		await asyncio.sleep(1)

		# Get browser state to find dropdown elements
		await browser_session.get_browser_state_summary()
		selector_map = await browser_session.get_selector_map()

		# Find the dropdowns
		employment_status_element = None
		hire_type_element = None

		for idx, element in selector_map.items():
			if element.attributes.get('id') == 'employment-status':
				employment_status_element = idx
			elif element.attributes.get('id') == 'hire-type':
				hire_type_element = idx

		assert employment_status_element is not None, 'Could not find employment-status dropdown'
		assert hire_type_element is not None, 'Could not find hire-type dropdown'

		# Create a model for the standard select_dropdown action
		class SelectDropdownModel(ActionModel):
			select_dropdown: dict

		# Select "Part Time" from employment status dropdown
		result = await tools.act(
			SelectDropdownModel(select_dropdown={'index': employment_status_element, 'text': 'Part Time'}),
			browser_session,
		)
		assert result.error is None, f'Failed to select employment status: {result.error}'

		# Select "W-2" from hire type dropdown
		result = await tools.act(
			SelectDropdownModel(select_dropdown={'index': hire_type_element, 'text': 'W-2'}),
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

		# THIS IS THE KEY TEST: React state should have captured both selections
		assert (
			submitted['employmentStatus'] == 'partTime'
		), f"Expected 'partTime', got {submitted['employmentStatus']}"
		assert submitted['hireType'] == 'w-2', f"Expected 'w-2', got {submitted['hireType']}"

		# Also verify the result is displayed on the page using CDP
		cdp_session = await browser_session.get_or_create_cdp_session()
		page_text_result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'document.body.textContent', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		page_text = page_text_result.get('result', {}).get('value', '').lower()

		assert 'form submitted successfully' in page_text, 'Success message not found'
		assert 'part time' in page_text, 'Employment status not displayed in result'
		assert 'w-2' in page_text, 'Hire type not displayed in result'
