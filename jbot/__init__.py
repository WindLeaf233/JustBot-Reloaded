from .utils import Logger, MessageChain, Listener, ListenerManager, Role
from .apis import Adapter, Config, Event, Element, Contact, Matcher
from .utils.utils import pretty_function
from .matchers import CommandMatcher, KeywordMatcher

from typing import Dict, Type, Union, Coroutine, Any, List, Awaitable, Tuple
from rich.traceback import install

import asyncio

install()
VERSION = '2.2.0'
HTTP_PROTOCOL = 'http://'
WS_PROTOCOL = 'ws://'
CONFIG = Config(*[None] * 6)


class BotApplication:
    """
    > 说明
        机器人实例类.
    > 参数
        + adapter [Adapter]: 适配器实例
    """

    def __init__(self, adapter: Adapter) -> None:
        self.adapter = adapter
        self.nickname = self.coroutine(self.adapter.nick_name)
        self.listener_manager = ListenerManager()
        self.adapter_utils = self.adapter.utils
        self.message_handler = self.adapter.message_handler
        self.set_config()
        self.logger = Logger('Application/%s' % VERSION)

        self.logger.info('加载 JustBot<v%s> 中...' % VERSION)
        self.logger.info('使用的适配器: `%s`.' % adapter.name)
        self.logger.info('登录成功: `%s`.' % self.nickname)
        self.coroutine(self.adapter.check())

    def set_config(self) -> None:
        for k in self.__dict__.keys():
            CONFIG.__setattr__(k, self.__dict__[k])
        CONFIG.__setattr__('application', self)

    def start_running(self) -> None:
        self.coroutine(self.adapter.start_listen())

    async def send_msg(self, target: Contact,
                       message: Union[MessageChain, Union[Element, List[Element], Tuple[Element]], str]) -> None:
        """
        > 说明
            向联系人发送消息.
        > 参数
            + target [Contact]: 联系人实例
            + message [MessageChain | Element | str]: 消息链或元素或纯文本 (纯文本会自动转为 ``Plain``, 元素会自动转化为 ``MessageChain``)
        > 示例
            >>> friend = Friend(123456789)
            >>> await app.send_msg(friend, MessageChain.create(Reply(123456789), Plain('Example Message')))
            >>> await app.send_msg(friend, Plain('Single Element'))
            >>> await app.send_msg(friend, [Plain('A List or Tuple Too'), Face(12)])
            >>> await app.send_msg(friend, 'Example Message')
        """

        try:
            t = type(message)
            send = lambda chain: self.adapter.send_message(target, chain)
            elements = Element.__subclasses__()
            error = lambda: self.adapter.logger.warning('无法发送消息: 参数 [light_green]`message`[/light_green] 类型错误!')
            is_element = t in elements or t is Element
            is_list = t in [list, tuple]

            if t is MessageChain:
                await send(message)
            elif t is str:
                plain: Element = \
                    [[k for k in i.__subclasses__() if k.__name__ == 'Plain']
                     for i in elements
                     if self.adapter.name.lower() in str(i).lower()
                    ][0][0](message)
                await send(MessageChain.create(plain))
            elif is_element or is_list:
                if is_element:
                    await send(MessageChain.create(message))
                elif is_list:
                    await send(MessageChain.create(*message))
                else:
                    error()
            else:
                error()
        except Exception as e:
            self.adapter.logger.error('无法发送消息: `%s`' % str(e))
            raise

    @staticmethod
    def coroutine(coroutine: Union[Coroutine, Any]) -> Any:
        return asyncio.run(coroutine)

    def on(self, event: Union[List[Type[Event]], Tuple[Type[Event]], Type[Event]], priority: int = 5) -> 'wrapper':
        """
        > 说明
            添加事件监听器.
        > 参数
            + event [type[Event] | list[type[Event]] | tuple[type[Event]]]: 事件类型
            + priority [int]: 优先级 (越小越优先, 不能小于 0) [default=5]
        """

        if type(priority) is not int:
            self.logger.error('无法注册监听器: 参数优先级类型错误!')
            return lambda target: target

        if priority > 0:
            def wrapper(target: Awaitable) -> Awaitable:
                if asyncio.iscoroutinefunction(target):
                    ev = event
                    
                    if ev.__class__ == list and len(list(ev)) == 1:
                        ev = ev[0]
                    join = lambda e: self.listener_manager.join(listener=Listener(e, target), priority=priority)
                    register = lambda multi, name: self.logger.info('注册监听器%s: [blue]%s[red][%s][/red][/blue] => %s.' % (
                        ' (多个事件)' if multi else '', name, priority, pretty_function(target)))

                    if ev.__class__ not in [list, tuple]:
                        register(True, ev.__name__)
                        join(ev)
                    else:
                        register(False, ' & '.join([e.__name__ for e in ev]))
                        for e in ev:
                            join(e)
                else:
                    self.logger.warning('无法注册监听器: 已忽略函数 [light_green]%s[/light_green], 它必须是异步函数!' % pretty_function(target))    
                return target
            return wrapper
        else:
            self.logger.error('无法注册监听器: 优先级不能小于 0!')
    
    def __set_decorator(self, value: Any, type: str, desc: str) -> 'wrapper':
        def wrapper(target: Awaitable) -> Awaitable:
            mapping = {
                'matcher': lambda: self.listener_manager.set_matcher(target, value),
                'param_convert': lambda: self.listener_manager.set_param_convert(target, value),
                'role': lambda: self.listener_manager.set_role(target, value),
                'nlp': lambda: self.listener_manager.set_nlp(target, value)
            }
            flag = mapping[type]()
            if not flag:
                self.logger.warning('无法设置%s: 函数 %s 不是一个监听器, 请检查参数及装饰顺序!' %
                                   (desc, pretty_function(target)))
            return target
        return wrapper
    
    def command(self, command: Union[List[str], Tuple[str], str],
                match_all_width: bool = False, ignore: Union[List[Type[Element]], Tuple[Type[Element]]] = ()) -> 'wrapper':
        """
        > 说明
            装饰函数为命令匹配器.
        > 参数
            + command [list[str] | tuple[str] | str]: 命令字符串或列表
            + match_all_width [bool]: 是否同时匹配半角和全角 [default=False]
            + ignore [list[type[Element]]]: 忽略消息中的元素, 如忽略 `At`, `Reply` [defualt=()]
        """
        command_matcher = CommandMatcher(command=command, match_all_width=match_all_width, ignore=ignore)
        return self.__set_decorator(command_matcher, 'matcher', '消息匹配器')

    def keyword(self, keyword: Union[List[str], Tuple[str], str],
                match_all_width: bool = False, ignore: Union[List[Type[Element]], Tuple[Type[Element]]] = ()):
        """
        > 说明
            装饰函数为关键词匹配器.
        > 参数
            + keyword [list[str] | tuple[str] | str]: 关键词字符串或列表
            + match_all_width [bool]: 是否同时匹配半角和全角 [default=False]
            + ignore [list[type[Element]]]: 忽略消息中的元素, 如忽略 `At`, `Reply` [defualt=()]
        """
        keyword_matcher = KeywordMatcher(keyword=keyword, match_all_width=match_all_width, ignore=ignore)
        return self.__set_decorator(keyword_matcher, 'matcher', '消息匹配器')
    
    def matcher(self, matcher: Matcher) -> 'wrapper':
        """
        > 说明
            [已弃用] 请使用 `@bot.command` 和 `@bot.keyword`
            
            设置消息事件匹配器.
        > 参数
            + matcher [Matcher]: 消息匹配器
        """
        
        return self.__set_decorator(matcher, 'matcher', '消息匹配器')

    def param_convert(self, param_convert: Type[Union[str, list, dict, None]]) -> 'wrapper':
        """
        > 说明
            设置消息事件参数转换类型.
        > 参数
            + param_convert [type[str] | type[list] | type[dict] | None]: 消息事件中命令参数转换类型
        """
        
        return self.__set_decorator(param_convert, 'param_convert', '参数转换类型')

    def role(self, role: Union[Role, List[Role], Tuple[Role]], todo: Awaitable = None) -> 'wrapper':
        """
        > 说明
            设置消息事件权限组. 如果不在指定权限组中则会执行 `todo` 或直接忽略事件.
        > 参数
            + target [Role | list[Role] | tuple[Role]]: 权限组
            + todo [Optional] [Awaitable]: 如果不在权限组执行的异步函数, 只能接受 `event`, `message`, `message_chain` 三个参数
        """
        
        return self.__set_decorator({'role': role, 'todo': todo}, 'role', '权限组')
    
    def nlp(self, c: float, keywords: Union[List[str], Tuple[str]], params: Dict[str, str]) -> 'wrapper':
        """
        > 说明
            绑定函数为自然语言处理器.
        > 参数
            + c [float]: 置信度
            + keywords [list[str] | tuple[str]]: 关键词
            + params: [dict[str, str]]: 需要处理的参数, 格式为 `参数名 -> 词语成分`
        """
        
        return self.__set_decorator({'c': c, 'keywords': keywords, 'params': params}, 'nlp', '自然语言处理')
