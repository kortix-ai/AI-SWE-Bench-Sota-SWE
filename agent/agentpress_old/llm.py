from typing import Union, Dict, Any
import litellm
import os
import json
import openai
from openai import OpenAIError
import asyncio
import logging
from langfuse.decorators import langfuse_context, observe
# import agentops

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
AGENTOPS_API_KEY = os.environ.get('AGENTOPS_API_KEY')

LANGFUSE_PUBLIC_KEY = os.environ.get('LANGFUSE_PUBLIC_KEY', '')
LANGFUSE_SECRET_KEY = os.environ.get('LANGFUSE_SECRET_KEY', '')
LANGFUSE_HOST = os.environ.get('LANGFUSE_HOST', 'https://cloud.langfuse.com')

os.environ['LANGFUSE_PUBLIC_KEY'] = LANGFUSE_PUBLIC_KEY
os.environ['LANGFUSE_SECRET_KEY'] = LANGFUSE_SECRET_KEY
os.environ['LANGFUSE_HOST'] = LANGFUSE_HOST

litellm.success_callback = ["langfuse"]
litellm.failure_callback = ["langfuse"]

os.environ['OPENAI_API_KEY'] = OPENAI_API_KEY
os.environ['ANTHROPIC_API_KEY'] = ANTHROPIC_API_KEY
os.environ['GROQ_API_KEY'] = GROQ_API_KEY

# agentops.init(AGENTOPS_API_KEY)
# os.environ['LITELLM_LOG'] = 'DEBUG'

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def make_llm_api_call(messages, model_name, response_format=None, temperature=0, max_tokens=None, tools=None, tool_choice="auto", api_key=None, api_base=None, agentops_session=None, stream=False, top_p=None):
    litellm.set_verbose = True

    async def attempt_api_call(api_call_func, max_attempts=3):
        for attempt in range(max_attempts):
            try:
                return await api_call_func()
            except litellm.exceptions.RateLimitError as e:
                logger.warning(f"Rate limit exceeded. Waiting for 30 seconds before retrying...")
                await asyncio.sleep(30)
            except OpenAIError as e:
                logger.info(f"API call failed, retrying attempt {attempt + 1}. Error: {e}")
                await asyncio.sleep(5)
            except json.JSONDecodeError:
                logger.error(f"JSON decoding failed, retrying attempt {attempt + 1}")
                await asyncio.sleep(5)
        raise Exception("Failed to make API call after multiple attempts.")

    async def api_call():
        # Retrieve the current Langfuse trace ID
        trace_id = langfuse_context.get_current_trace_id()
        metadata = {}
        if trace_id:
            metadata["trace_id"] = trace_id

        api_call_params = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "response_format": response_format,
            "top_p": top_p,
            "stream": stream,
            "metadata": metadata,  # Include metadata with trace_id
        }

        # Add api_key and api_base if provided
        if api_key:
            api_call_params["api_key"] = api_key
        if api_base:
            api_call_params["api_base"] = api_base

        # Use 'max_completion_tokens' for 'o1' models, otherwise use 'max_tokens'
        if 'o1' in model_name:
            if max_tokens is not None:
                api_call_params["max_completion_tokens"] = max_tokens
        else:
            if max_tokens is not None:
                api_call_params["max_tokens"] = max_tokens

        if tools:
            # Use the existing method of adding tools
            api_call_params["tools"] = tools
            api_call_params["tool_choice"] = tool_choice

        def add_cache_control_to_content(content):
            if isinstance(content, list):
                return [
                    item if isinstance(item, dict) and "cache_control" in item 
                    else {"type": "text", "text": item, "cache_control": {"type": "ephemeral"}} 
                    for item in content
                ]
            elif isinstance(content, dict):
                if "cache_control" not in content:
                    content["cache_control"] = {"type": "ephemeral"}
                return content
            return content

        if "claude" in model_name.lower() or "anthropic" in model_name.lower():
            api_call_params["extra_headers"] = {
                "anthropic-beta": "max-tokens-3-5-sonnet-2024-07-15"
            }
            # Add cache control to messages for Anthropic models
            processed_messages = []
            for msg in messages:
                processed_msg = msg.copy()
                processed_msg["content"] = add_cache_control_to_content(msg["content"])
                processed_messages.append(processed_msg)
            api_call_params["messages"] = processed_messages
        
        # Log the API request
        logger.info(f"Sending API request: {json.dumps(api_call_params, indent=2)}")

        if agentops_session:
            response = await agentops_session.patch(litellm.acompletion)(**api_call_params)
        else:
            response = await litellm.acompletion(**api_call_params)

        # Log the API response
        logger.info(f"Received API response: {response}")

        return response

    return await attempt_api_call(api_call)

# Sample Usage
if __name__ == "__main__":
    import asyncio
    async def test_llm_api_call(stream=True):
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Complex essay on economics"}
        ]
        model_name = "gpt-4o"

        response = await make_llm_api_call(messages, model_name, stream=stream)

        if stream:
            print("Streaming response:")
            async for chunk in response:
                if isinstance(chunk, dict) and 'choices' in chunk:
                    content = chunk['choices'][0]['delta'].get('content', '')
                    print(content, end='', flush=True)
                else:
                    # For non-dict responses (like ModelResponse objects)
                    content = chunk.choices[0].delta.content
                    if content:
                        print(content, end='', flush=True)
            print("\nStream completed.")
        else:
            print("Non-streaming response:")
            if isinstance(response, dict) and 'choices' in response:
                print(response['choices'][0]['message']['content'])
            else:
                # For non-dict responses (like ModelResponse objects)
                print(response.choices[0].message.content)

    # Example usage:
    # asyncio.run(test_llm_api_call(stream=True))  # For streaming
    # asyncio.run(test_llm_api_call(stream=False))  # For non-streaming

    asyncio.run(test_llm_api_call())