# Hospital Appointment Agent

A chat assistant that books hospital appointments. A Streamlit page talks to a Python agent
(no Foundry agent service), and every model call goes through Azure API Management (APIM)
to Azure OpenAI. Confirmed bookings are saved in a SQLite database.

```
Streamlit page (app.py) -> Agent (agent/) -> APIM gateway -> Azure OpenAI
                                 |
                                 +-> bookings.db
```

## Run it

1. Install: `pip install -r requirements.txt`
2. Create a `.env` file next to `app.py`:

   ```
   APIM_GATEWAY_URL=https://<your-apim-name>.azure-api.net
   APIM_SUBSCRIPTION_KEY=<your APIM subscription key>
   AOAI_API_VERSION=2024-10-21
   AOAI_DEPLOYMENT=<your model deployment name>
   ```

3. Start: `streamlit run app.py`

Try: "Book me a cardiology appointment next Monday at 10, my name is Lena."

## Azure requirements

- An Azure OpenAI resource with a deployed chat model (use a current one, for example `gpt-4.1-mini`).
- An APIM API with URL suffix `openai`, Web service URL `https://<openai-resource>.openai.azure.com/openai`,
  the operation `POST /deployments/{deployment-id}/chat/completions`, and the subscription key header set to `api-key`.
- APIM's managed identity needs the role **Cognitive Services OpenAI User** on the Azure OpenAI resource.

## Common errors

| Error | Fix |
|---|---|
| `404 Resource not found` | Wrong `AOAI_API_VERSION`. Use `2024-10-21` (a model version like `2024-11-20` is not an API version). |
| `404 DeploymentNotFound` | `AOAI_DEPLOYMENT` does not match a deployment in your Azure OpenAI resource. |
| `401 PermissionDenied` | APIM's identity is missing the role above. |
| "Missing setting ..." | `.env` is missing or incomplete. |

## Notes

- Keep `.env` and `bookings.db` out of git (they are in `.gitignore`).
- Doctors and time slots are demo data.
- Regenerate the APIM subscription key if it is ever shared.
