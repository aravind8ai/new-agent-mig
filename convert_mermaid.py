import base64
import re

readme_path = "/Users/vasan/2 Areas/Repo/innovathon/README.md"

with open(readme_path, "r") as f:
    content = f.read()

# Regex to find mermaid blocks
pattern = r"```mermaid\n(.*?)\n```"

def replace_mermaid(match):
    mermaid_code = match.group(1)
    # Encode for mermaid.ink
    # Format: https://mermaid.ink/img/<base64>
    # Need to construct the object: {"code":..., "mermaid": {...}}
    # But simple base64 of the code string often works for simple graphs? 
    # Actually mermaid.ink expects base64 of the code.
    
    encoded = base64.urlsafe_b64encode(mermaid_code.encode("utf-8")).decode("utf-8")
    
    # Create Markdown Image
    return f"![Architecture Diagram](https://mermaid.ink/img/{encoded})\n\n<details><summary>View Mermaid Code</summary>\n\n```mermaid\n{mermaid_code}\n```\n</details>"

new_content = re.sub(pattern, replace_mermaid, content, flags=re.DOTALL)

with open(readme_path, "w") as f:
    f.write(new_content)

print("Updated README with Mermaid Images.")
