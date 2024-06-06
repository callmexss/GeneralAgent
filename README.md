# GeneralAgent: From LLM to Agent

GeneralAgent是一个python原生的Agent框架，可以配置角色、工具、知识库来快速生成Agent，并通过函数调用(agent.run)来完成命令和输出结构化内容。

GeneralAgent有以下特性:

* GeneralAgent 不依赖大模型的 function call，通过python代码解释器来调用工具，可以直接传递python函数给Agent使用
* GeneralAgent 支持序列化，随用随启
* GeneralAgent 支持自我调用和堆栈记忆，用最少的大模型消耗，来完成复杂任务，请见[论文](./docs/paper/General_Agent__Self_Call_And_Stack_Memory.pdf)
* GeneralAgent 开发的应用，可以通过 [AgentServer(开源准备中)](https://github.com/CosmosShadow/AgentServer) 进行部署，快速给大规模用户提供Agent服务



## 安装

```bash
pip install GeneralAgent
```



## 使用

```python
# 写小说
from GeneralAgent.agent import Agent
from GeneralAgent import skills

agent = Agent('你是一个小说家')
# topic = skills.input('请输入小说的名称和主题: ')
topic = '小白兔吃糖不刷牙的故事'
summary = agent.run(f'小说的名称和主题是: {topic}，扩展和完善一下小说概要。要求具备文艺性、教育性、娱乐性。', return_type=str)
chapters = agent.run('输出小说的章节名称和每个章节的概要，返回列表 [(chapter_title, chapter_summary), ....]', return_type=list)
contents = []
for index, (chapter_title, chapter_summary) in enumerate(chapters):
    content = agent.run(f'对于章节: {chapter_title}\n{chapter_summary}. \n输出章节的详细内容，注意只返回内容，不要标题。', return_type=str)
    content = '\n'.join([x.strip() for x in content.split('\n')])
    contents.append(content)
with open('novel.md', 'w') as f:
    for index in range(len(chapters)):
        f.write(f'### {chapters[index][0]}\n')
        f.write(f'{contents[index]}\n\n')
skills.output('你的小说已经生成[novel.md](novel.md)\n')

# 删除Agent: 记忆文件 + python序列化状态
# agent.delete()
```

更多例子请见[examples](./examples)



## 论文

[General Agent：自调用和堆栈内存](./docs/paper/General_Agent__Self_Call_And_Stack_Memory.pdf)



## 加入我们

使用微信扫描下方二维码

<p align="center">
<img src="./docs/images/wechat.jpg" alt="wechat" width=400/>
</p>