**Objective**
Given the user chat history, generate continuation messages that the user can use to continue the conversation. Reply with a JSON array. 

**Example 1**
<chat_history>
  <msg role = "user"> What is a banana ? </msg>
  <msg role = "ai"> banana is a fruit </msg>
</chat_history>

Output: 
["what is the color of a banana ?", "what is the shape of a banana ?", "what can you do with a banana ?"]

**Example 2**
<chat_history />

Output: 
["Get me publications on HIV", "Show me the files I have", "Tell me about clinical trials related to HPV"]