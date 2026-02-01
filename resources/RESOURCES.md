# CSE Exercise - Supplementary Resources

This document contains detailed references, API documentation, and best practices to support your implementation. Not all content is mandatory - use what you need.

## Mandatory Context

**Getting Started with Postman:**
- **Free Account:** Sign up at [postman.com](https://www.postman.com/) - free account
- **API Key:** Generate from your account settings > API Keys ([docs](https://learning.postman.com/docs/developer/postman-api/authentication/#generate-a-postman-api-key))
- **Workspace ID:** Create a workspace, then find the ID in the URL (e.g., `https://postman.com/workspace/{workspace-id}`)
- **Free tier includes:** Spec Hub, collection generation, environments, basic API calls (sufficient for this exercise)

**Key Postman Concepts:**
- **Spec Hub:** Centralized repository for API specifications (OpenAPI, AsyncAPI) serving as single source of truth
- **Collection:** Group of API requests with tests, documentation, and workflows
- **Workspace:** Collaborative space for organizing collections, specs, and environments
- **Domain Sprint Model:** Phased approach to organize and activate APIs in one business domain, then scale to others

**Customer's Build Pipeline:**
- GitHub for source code control
- GitHub Actions for repo-level automation (your integration point)
- GitLab for build promotion (conceptual discussion only)
- AWS for deployment (API Gateway routes to serverless functions)
- Environments: Dev, QA, UAT, Prod

## Postman API Documentation

### Core Platform
- [Postman Learning Center](https://learning.postman.com/) - Complete documentation hub
- [What is Postman?](https://www.postman.com/product/what-is-postman/) - Platform overview
- [Using Workspaces](https://learning.postman.com/docs/collaborating-in-postman/using-workspaces/internal-workspaces/use-workspaces/) - Team collaboration

### API Ingestion & Import
- [Managing APIs and Spec Hub](https://learning.postman.com/docs/designing-and-developing-your-api/managing-apis/) - Creating and managing specs
- [Create a Spec Endpoint](https://www.postman.com/postman/postman-public-workspace/request/12959542-5fbbc5ec-d156-41e0-aa5c-d76b1f5bca03) - `POST /specs?workspaceId={{workspaceId}}`
- [Generate Collection from Spec](https://learning.postman.com/docs/designing-and-developing-your-api/developing-an-api/generating-collections-from-api-specifications/) - `POST /specs/{{specId}}/generations/collection`
- [Postman API Documentation](https://learning.postman.com/docs/developer/postman-api/make-postman-api-call/) - Programmatic access
- [Postman Public Workspace](https://www.postman.com/postman/postman-public-workspace/overview) - API examples

## Sample Implementation Patterns

### Example: Ingestion Script (Python)

```python
import requests
import json

POSTMAN_API_KEY = "your-api-key"
WORKSPACE_ID = "your-workspace-id"
BASE_URL = "https://api.getpostman.com"

headers = {
    "X-Api-Key": POSTMAN_API_KEY,
    "Content-Type": "application/json"
}

# Step 1: Create spec in Spec Hub
with open('payment-refund-api-openapi.yaml', 'r') as f:
    spec_content = f.read()

spec_payload = {
    "spec": {
        "name": "Payment Refund API",
        "content": spec_content,
        "contentType": "yaml"
    }
}

response = requests.post(
    f"{BASE_URL}/specs?workspaceId={WORKSPACE_ID}",
    headers=headers,
    json=spec_payload
)

spec_id = response.json()['spec']['id']
print(f"Created spec: {spec_id}")

# Step 2: Generate collection from spec
generation_payload = {
    "options": {
        "requestParametersResolution": "example",
        "exampleParametersResolution": "example"
    }
}

response = requests.post(
    f"{BASE_URL}/specs/{spec_id}/generations/collection",
    headers=headers,
    json=generation_payload
)

collection_id = response.json()['collection']['id']
print(f"Generated collection: {collection_id}")
```

### Example: JWT Auth Pre-Request Script

```javascript
// Pre-request script for JWT authentication
const clientId = pm.environment.get("client_id");
const clientSecret = pm.environment.get("client_secret");
const tokenUrl = pm.environment.get("token_url");

// Check if token is cached and still valid
const cachedToken = pm.environment.get("jwt_token");
const tokenExpiry = pm.environment.get("token_expiry");

if (cachedToken && tokenExpiry && Date.now() < tokenExpiry) {
    return; // Token still valid
}

// Request new token
pm.sendRequest({
    url: tokenUrl,
    method: 'POST',
    header: {
        'Content-Type': 'application/x-www-form-urlencoded'
    },
    body: {
        mode: 'urlencoded',
        urlencoded: [
            {key: 'grant_type', value: 'client_credentials'},
            {key: 'client_id', value: clientId},
            {key: 'client_secret', value: clientSecret}
        ]
    }
}, (err, response) => {
    if (err) {
        console.error('Token request failed:', err);
        return;
    }

    const jsonData = response.json();
    pm.environment.set("jwt_token", jsonData.access_token);
    pm.environment.set("token_expiry", Date.now() + (jsonData.expires_in * 1000));
});
```

### Example: GitHub Actions Workflow

```yaml
name: Sync API Specs to Postman

on:
  push:
    paths:
      - 'specs/**/*.yaml'
      - 'specs/**/*.json'

jobs:
  sync-specs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Update Spec in Postman
        run: |
          SPEC_ID="${{ secrets.POSTMAN_SPEC_ID }}"
          WORKSPACE_ID="${{ secrets.POSTMAN_WORKSPACE_ID }}"

          # Update spec content
          curl -X PUT "https://api.getpostman.com/specs/$SPEC_ID" \
            -H "X-Api-Key: ${{ secrets.POSTMAN_API_KEY }}" \
            -H "Content-Type: application/json" \
            -d @specs/payment-refund-api.json

      - name: Regenerate Collection
        run: |
          SPEC_ID="${{ secrets.POSTMAN_SPEC_ID }}"

          curl -X POST "https://api.getpostman.com/specs/$SPEC_ID/generations/collection" \
            -H "X-Api-Key: ${{ secrets.POSTMAN_API_KEY }}" \
            -H "Content-Type: application/json" \
            -d '{"options": {"requestParametersResolution": "example"}}'

      - name: Run Collection Tests
        run: |
          COLLECTION_ID="${{ secrets.POSTMAN_COLLECTION_ID }}"

          npx postman-cli collection run $COLLECTION_ID \
            --environment ${{ secrets.POSTMAN_ENVIRONMENT_ID }} \
            --api-key ${{ secrets.POSTMAN_API_KEY }}
```

## Test Pattern Examples

### Schema Validation Test

```javascript
pm.test("Response matches schema", function () {
    const schema = {
        type: "object",
        required: ["refundId", "status", "amount"],
        properties: {
            refundId: { type: "string", pattern: "^RFD-[0-9]{10}$" },
            status: { type: "string", enum: ["pending", "completed", "failed"] },
            amount: { type: "number", minimum: 0 },
            currency: { type: "string", pattern: "^[A-Z]{3}$" },
            transactionId: { type: "string" }
        }
    };

    pm.response.to.have.jsonSchema(schema);
});
```

### Error Scenario Coverage

```javascript
pm.test("401 Unauthorized - Missing token", function () {
    pm.expect(pm.response.code).to.equal(401);
    pm.expect(pm.response.json()).to.have.property('error', 'unauthorized');
});

pm.test("400 Bad Request - Invalid amount", function () {
    const body = pm.response.json();
    pm.expect(pm.response.code).to.equal(400);
    pm.expect(body.errors).to.be.an('array');
    pm.expect(body.errors[0].field).to.equal('amount');
});

pm.test("500 Server Error - Includes correlation ID", function () {
    pm.expect(pm.response.code).to.equal(500);
    pm.expect(pm.response.headers.get('X-Correlation-ID')).to.exist;
});
```

### Integration Chaining Pattern

```javascript
// Test 1: Create refund
pm.test("Refund created successfully", function () {
    const response = pm.response.json();
    pm.expect(response.refundId).to.exist;

    // Store for next request
    pm.environment.set("last_refund_id", response.refundId);
});

// Test 2: Get refund details (uses stored ID)
pm.test("Can retrieve refund by ID", function () {
    const refundId = pm.environment.get("last_refund_id");
    const response = pm.response.json();
    pm.expect(response.refundId).to.equal(refundId);
    pm.expect(response.status).to.be.oneOf(["pending", "completed"]);
});
```

## Frequently Asked Questions

**Q: Should I implement all 47 APIs for this exercise?**
A: No. Focus on one API (Refund API) with a complete implementation. Then articulate the scaling strategy for the remaining 46 APIs in your README and presentation.

**Q: Do I need to set up AWS API Gateway?**
A: No. Use the provided `payment-refund-api-openapi.yaml` sample spec. If you have AWS experience, you can optionally demonstrate the export process, but it's not required.

**Q: How much time should I spend on this?**
A: Target 4-6 hours total. Use AI assistants to accelerate coding. Focus your time on strategic thinking, value articulation, and presentation quality.

**Q: What programming language should I use?**
A: Whatever you're most comfortable with. Python, Node.js, and Bash are all common. Or use GitHub Actions YAML for a workflow-based approach.

**Q: Do I need to make the Postman API calls work end-to-end?**
A: Ideally yes, but it's not a hard requirement. At minimum, show the correct API call structure with proper request bodies. If you can't get API access, use mock/example responses to demonstrate your understanding.

**Q: Should my presentation be highly technical or business-focused?**
A: Both. You're presenting to a panel that includes technical leaders and business stakeholders. Balance technical depth with business value articulation.

## Evaluation Rubric

### Technical Execution (30%)

**4 - Exemplary:**
- Production-ready code with error handling
- Proper environment configuration and secrets management
- Reusable functions/modules for easy extension

**3 - Strong:**
- Clean, well-structured code
- Proper use of Postman API endpoints
- Works reliably for the demo scenario
- Basic error handling present

**2 - Baseline:**
- Script successfully runs and demonstrates core workflow
- Generates collection from spec
- May have rough edges but accomplishes the goal

**1 - Insufficient:**
- Code doesn't work or is incomplete
- Misunderstands core Postman concepts
- Major gaps in implementation

### Value Articulation (30%)

**4 - Exemplary:**
- Executive-level storytelling connecting technical work to business outcomes
- Quantified ROI with multiple dimensions (time, quality, risk)
- Addresses the $480K renewal decision explicitly
- Demonstrates understanding of enterprise buying dynamics

**3 - Strong:**
- Clear ROI calculation with realistic assumptions
- Articulates both time savings and quality improvements
- Connects solution to customer pain points
- Business metrics are measurable and trackable

**2 - Baseline:**
- Explains time savings with basic numbers
- Shows understanding of customer problem
- Basic business case present

**1 - Insufficient:**
- No ROI calculation or unrealistic numbers
- Focuses only on technical features without business context
- Doesn't connect to customer value

### Pattern Thinking (25%)

**4 - Exemplary:**
- Complete framework with templates and training materials
- Shows acceleration curve (Domain 1: 3 weeks, Domain 2: 1 week, Domain 3: self-service)
- Anticipates common variations and edge cases
- Includes governance model to prevent future sprawl

**3 - Strong:**
- Detailed scaling approach with realistic timeline
- Identifies key patterns to replicate
- Considers different API types and auth methods
- Shows understanding of organizational adoption

**2 - Baseline:**
- Mentions scaling to remaining APIs
- Basic outline of how to repeat
- Recognizes pattern is repeatable

**1 - Insufficient:**
- No scaling strategy or unrealistic plan
- Treats it as one-off solution
- Doesn't demonstrate reusability

### Co-Execution (15%)

**4 - Exemplary:**
- Customer enablement strategy with checkpoints
- Clear handoff plan ensuring independence by Day 90
- Training materials or documentation for customer team
- Identifies skills to transfer and how to measure success

**3 - Strong:**
- Knowledge transfer approach with specific activities
- Shows how customer team learns to own the solution
- Identifies where CSE vs customer does the work

**2 - Baseline:**
- Mentions working with customer team
- Basic explanation of partnership approach
- Recognizes need for knowledge transfer

**1 - Insufficient:**
- Treats it as CSE-only implementation
- No customer enablement consideration
- Doesn't address long-term ownership
