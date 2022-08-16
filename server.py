# 服务器文件
from asyncore import write
from gc import callbacks
from operator import truediv
from pickle import FALSE, TRUE
import socket
import json
import string
import threading
from concurrent.futures import ThreadPoolExecutor
import select
import traceback
import ctypes
import os
import schedule
from urllib.parse import unquote, quote



# 解析请求
class Request:
    def __init__(self):
        self.state_code = {
            200: {'title': "OK"},
            400: {'title': "Bad Request", 'form': 'Your request has bad syntax or is inherently impossible to satisfy.\n'},
            403: {'title': "Forbidden", 'form': 'You do not have permission to get file from this server.\n'},
            404: {'title': "Not Found", 'form': 'The requested file was not found on this server.\n'},
            500: {'title': "Internal Error", 'form': 'There was an unusual problem serving the requested file.\n'},
        }

    # 编码请求
    def encode(self, code: int, request: dict, fd: int):
        print(code)
        if(code == 200):
            path = '%s%s'%('./root', request['path'][0])
            title = self.state_code[code]['title']
            file_size = os.path.getsize(path)
            keep = True if ('keep_alive' in request["path"] and request["path"]['keep_alive'] == 'True') else False

            ret_head = f"HTTP/1.1 {code} {title}\r\n"
            ret_head += f"Content-Length: {file_size}\r\n"
            ret_head += f"Content-Type: text/html\r\n"
            keep_alive = 'keep_alive' if keep else "close"
            ret_head += f"Connection: {keep_alive}\r\n"
            ret_head += '\r\n'

            self.rerespone_data[fd] = {
                'head': bytes(ret_head),
                'body': {
                    'f': open(path, 'rb'),
                    'offset': 0,
                    'count': os.path.getsize(path)
                }
            }
            self.modify(fd, epoll_out=True)
            return (True, fd)
        else:
            return (True, fd)
    # 解码请求
    def decode(self, r):
        self.content = r
        self.path = r.split()[1]
        self.body = r.split('\r\n\r\n', 1)[1]

        ret = {}
        ret['method'] = r.split()[0]
        ret['path'] = self.parse_path()
        ret['header'] = self.headers()
        ret['body'] = self.form_body()
        return ret

    def form_body(self):
        if (len(self.body) == 0):
            return {}
        return self._parse_parameter(self.body)

    def parse_path(self):
        index = self.path.find('?')
        if index == -1:
            return self.path, {}
        else:
            path, query_string = self.path.split('?', 1)
            query = self._parse_parameter(query_string)
            return path, query
   
    def headers(self):
        header_content = self.content.split('\r\n\r\n', 1)[0].split('\r\n')[1:]
        result = {}
        for line in header_content:
            k, v = line.split(': ')
            result[quote(k)] = quote(v)
        return result

    @staticmethod
    def _parse_parameter(parameters):
        args = parameters.split('&')
        query = {}
        for arg in args:
            k, v = arg.split('=')
            query[k] = unquote(v)
        return query

class Server(Request):
    def __init__(self, address, port, backlog=128, 
                num_works=8, time_inter=1):
        """
            address: 绑定地址，一般是本地地址
            port: 端口
            backlog: 半连接队列
            num_works: 线程池数量
            pipe: 命名管道
            time_inter: 定时器间隔
        """
        
        # TCP相关
        self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)        # TCP
        self.listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)      # IO复用
        self.listen_socket.bind((address, port))                                      # 地址和端口绑定
        self.listen_socket.listen(backlog)
        self.listen_socket.setblocking(0)                                             # 非阻塞模式

        # EPOLL相关
        self.epoll = select.epoll()
        self.epoll.register(self.listen_socket.fileno(), select.EPOLLIN)              # listen注册socket
    
        # 线程池对象
        self.th_pool = ThreadPoolExecutor(max_workers=num_works)
        
        # 定时连接控制
        self.time_inter = time_inter

        # 处理请求函数
        self.respone_func = {
            'GET': self.deal_get,
            'POST': self.deal_post
        }

    def run(self):
        try:      
            self.connections, self.respone_data, self.request = {}, {}, {}
            while True:
                events = self.epoll.poll(self.time_inter)
                for fileno, event in events:
                    # 新连接
                    if fileno == self.listen_socket.fileno():
                        client_socket, addr = self.listen_socket.accept()
                        self.epoll.register(client_socket.fileno(), select.EPOLLIN | select.EPOLLONESHOT)
                        self.connections[client_socket.fileno()] = client_socket
                        client_socket.setblocking(0)
                        print('新连接')
                    else:
                        if (event & select.EPOLLIN or event & select.EPOLLOUT):
                            t = self.th_pool.submit(self.action, fileno, event) 
                            t.add_done_callback(self.callback)
        finally:
            # 关闭对应的文件描述符
            self.epoll.unregister(self.listen_socket.fileno())
            self.epoll.close()
            self.listen_socket.close()
        
    def action(self, fd, event):
        if (event & select.EPOLLIN):
            try:
                rev_str = self.connections[fd].recv(1024).decode('utf-8')
                request = self.decode(rev_str)
                self.request[fd] = request
                return self.respone_func[request['method']](request, fd)
                
            except :
                # 输出错误原因
                print(traceback.format_exc())
                return (False, fd)

        if(event & select.EPOLLOUT):
            print('out 事件')
            try:
                # 发送头
                if('head' in self.respone_data[fd]):
                    self.connections[fd].send(self.respone_data[fd]['head'])
                    self.respone_data[fd].pop('head')
                
                offset = self.respone_data[fd]['body']['offset']
                byte_num = self.respone_data[fd]['body']['count'] - offset
                file_no = self.respone_data[fd]['body']['f'].fileno()

                if(byte_num> 0):
                    send_num = os.sendfile(fd, file_no, offset, byte_num)
                    self.respone_data[fd]['body']['offset'] += send_num
                else:
                    keep_alive = True if ('keep_alive' in request["path"] and request["path"]['keep_alive'] == 'True') else False
                    if(keep_alive):
                        self.modify(fd, epoll_in=True)
                        return (fd, True)
                    else:
                        return (fd, False)
                return (False, fd)

            except :
                # 输出错误原因
                print(traceback.format_exc())
                return (False, fd)
    # 处理get
    def deal_get(self, request: list, fd: int) -> tuple:
        req_path = '%s%s'%('./root', request['path'][0])
        print(req_path)
        # 权限核对
        state_code = 200
        if(os.path.exists(req_path) is False):
            state_code = 404
        return self.encode(state_code, request, fd)

    # 处理post
    def deal_post(self, request):
        pass

    # 修改一个文件描述符
    def modify(self, fd,
                     epoll_in=False,
                     epoll_out=False,
                     epoll_oneshort=True,
                     epoll_et = True):
        figs = [select.EPOLLIN, select.EPOLLOUT, select.EPOLLONESHOT, select.EPOLLET]
        args = [epoll_in, epoll_out, epoll_oneshort, epoll_et]
        set_fig = 0 
        for arg, fig in zip(args, figs):
            if arg:
                set_fig |= fig
        self.epoll.modify(fd, set_fig)

    # 清除一个连接
    def clear_connect(self, fd):
        self.epoll.unregister(fd)
        self.connections[fd].close()
        if(fd in self.respone_data):
            if('body' in self.respone_data):
                self.respone_data[fd]['body']['f'].close()
            self.respone_data.pop(fd)
        del self.connections[fd]

    def callback(self, ret):
        res = ret.result()
        if(res[0] == False):
            self.clear_connect(res[1])

