
**Hospital Appointment Agent**

A chat assistant that books hospital appointments. A Streamlit page talks to a hand-written Python agent, and every model call goes through Azure API Management (APIM) to Azure OpenAI.

**Code-based agent**: the tool-calling loop is plain Python (agent/agent.py). It does not use the Azure AI Foundry agent service.
APIM Developer tier sits in front of the model: clients only hold an APIM key, and a policy applies the token limit.
Bookings are stored in a SQLite database (bookings.db), only after a booking is confirmed.
**Streamlit page ──> Agent loop (Python) ──> APIM gateway ──(managed identity)──> Azure OpenAI
 app.py            agent/agent.py           subscription key,                    your model
                   agent/booking.py         token limit policy                   deployment
                        │
                        └──> bookings.db (SQLite)**
**Project layout**
Path	What it is
app.py	The whole front end: page, styling and UI helpers in one file
agent/agent.py	Agent loop and the general tools (calculator, time, notes)
agent/booking.py	Booking tools and the database code
infra/main.bicep, infra/deploy.sh	Optional: create APIM and Azure OpenAI from code
.env	Your settings (never commit this)
bookings.db	Created on first use, next to app.py

If you also have ui.py, style.css or .streamlit/config.toml from an earlier version, app.py no longer uses them.

**Quick start**

You need Python 3.10 or newer and a working gateway and model deployment (see Azure setup below).

**bash**
pip install -r requirements.txt

**Create a .env file next to app.py:**
APIM_GATEWAY_URL=https://<your-apim-name>.azure-api.net
APIM_SUBSCRIPTION_KEY=<your APIM subscription key>
AOAI_API_VERSION=2024-10-21
AOAI_DEPLOYMENT=<your model deployment name>

Then, from the folder that contains app.py:

bash
streamlit run app.py

Try: "Book me a cardiology appointment next Monday at 10, my name is Lena." The assistant checks availability, repeats the details back, and books only after you confirm.

**Optional settings:** ORG_NAME (shown in the page title, default "Hospital") and BOOKINGS_DB (a different path for the database file).

You can also test the agent without the page: python agent/agent.py.

**Azure setup**

The agent needs three things in Azure. Skip any you already have.

1. An Azure OpenAI resource with a model deployment. In the Foundry portal or with the CLI, deploy a current chat model, for example:

bash
**az cognitiveservices account deployment create \
  -g <resource-group> -n <openai-resource> \
  --deployment-name <deployment-name> \
  --model-name gpt-4.1-mini --model-version 2025-04-14 --model-format OpenAI \
  --sku-name Standard --sku-capacity 10**

Older models, such as gpt-4o-mini 2024-07-18, have been retired and are refused. Run az cognitiveservices account list-models -g <rg> -n <openai-resource> -o table to see what your resource offers, and use the deployment name in .env.

2. An APIM API in front of it (Developer tier is fine for testing, but has no SLA):

**API URL suffix: openai
Web service URL: https://<openai-resource>.openai.azure.com/openai
Operation: POST /deployments/{deployment-id}/chat/completions with a deployment-id template parameter
Subscription: required, header name api-key (the header the Azure OpenAI SDK sends)**

3. Permission for APIM to call the model. Turn on APIM's system-assigned identity and give it the role Cognitive Services OpenAI User on the Azure OpenAI resource. This needs someone with Owner or User Access Administrator rights. Then use this inbound policy on the API:
**
xml
<policies>
  <inbound>
    <base />
    <authentication-managed-identity resource="https://cognitiveservices.azure.com" output-token-variable-name="msi-token" ignore-error="false" />
    <set-header name="Authorization" exists-action="override">
      <value>@("Bearer " + (string)context.Variables["msi-token"])</value>
    </set-header>
    <set-header name="api-key" exists-action="delete" />
  </inbound>
  <backend><base /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>**

To check the gateway before running the page:

bash
curl -i -X POST "https://<apim-name>.azure-api.net/openai/deployments/<deployment-name>/chat/completions?api-version=2024-10-21" \
  -H "api-key: <subscription key>" -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hi"}]}'

HTTP/1.1 200 with a JSON reply means it works.

Optional: create it all from code

infra/deploy.sh <suffix> <email> [region] deploys APIM, Azure OpenAI, the role assignment and a token-limit policy with Bicep, and writes .env. It takes about 30 to 45 minutes. Before you use it:

The Bicep default model (gpt-4o-mini 2024-07-18) is retired. Pass a current model with modelName and modelVersion, or edit the defaults in infra/main.bicep.
The script writes AOAI_API_VERSION=2024-06-01. Change it to 2024-10-21 (or newer, see below) in .env.

Tear everything down later with az group delete -n rg-apim-agent-<suffix> --yes.

**Bookings**
**Departments**: general medicine, cardiology, pediatrics, orthopedics, dermatology (demo doctors).
**Hours**: Monday to Friday, slots at 09:00, 10:00, 11:00, 12:00, 14:00, 15:00 and 16:00, up to 60 days ahead.
**Storage**: a booking is saved only after every check passes. The database refuses two bookings for the same department, date and time.
**Tools the agent can use**: list departments, check availability, book, list bookings, cancel a booking.
**Viewing data**: open bookings.db with any SQLite viewer, or run python -c "import sqlite3; print(sqlite3.connect('bookings.db').execute('select * from bookings').fetchall())" from the folder that contains app.py.

The doctors and slots are demo data, not a real hospital schedule. To connect a real booking system, replace the functions in agent/booking.py and keep their names and return values.

Troubleshooting
Error	Likely cause and fix
404 Resource not found (code "404")	The api-version is wrong. Use a real API version such as 2024-10-21. A model version like 2024-11-20 is not an API version. Newer models can need a newer API version: copy it from View code in the Foundry playground. Also check the APIM API URL suffix and Web service URL.
404 DeploymentNotFound	No deployment with that name exists in the Azure OpenAI resource the APIM backend points to. Check AOAI_DEPLOYMENT in .env, and list deployments with az cognitiveservices account deployment list.
401 PermissionDenied, "lacks the required data action"	APIM's identity has no role on the Azure OpenAI resource. Assign Cognitive Services OpenAI User and wait a few minutes.
401 PermissionDenied, "Principal does not have access to API/Operation"	APIM is sending the key instead of the managed identity token, or key access is disabled on the resource. Use the managed identity policy above.
401 "Access denied due to missing subscription key"	The key is missing, or the APIM header name is not api-key.
429	The token limit was reached. Wait a minute.
"Missing setting ..." in the page	.env is missing or incomplete. Check that it sits next to app.py and has all four lines.
bookings.db is empty	Rows are added only after a confirmed booking (the assistant replies with an ID like BK-1A2B3C). Also check that you replaced agent/booking.py with the new version.

Stop Streamlit (Ctrl+C) and start it again after you change .env or any code.

Security notes
Keep .env and bookings.db out of git (add them to .gitignore).
The APIM subscription key is a secret. Regenerate it in APIM (Subscriptions) if it is ever shared.
bookings.db holds patient names. This demo has no login, and the assistant will list bookings for anyone who asks. Add authentication and require the patient's identity before using it with real data.
The assistant gives no medical advice, and the page tells users to call the local emergency number in an emergency.
Extending
Add a tool: write a function, add it to TOOLS and its schema to TOOL_SCHEMAS (general tools in agent/agent.py, booking tools in agent/booking.py).
Change the model: deploy another model in Azure OpenAI and update AOAI_DEPLOYMENT (and AOAI_API_VERSION if needed).
Change the look: everything visual is in app.py, in the CSS string near the top.
