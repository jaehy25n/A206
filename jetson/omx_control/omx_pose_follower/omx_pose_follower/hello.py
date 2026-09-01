import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState

class HelloNode(Node):
    def __init__(self):
        super().__init__('hello')
        self.count = 0

        self.subscription = self.create_subscription(
            JointState,
            '/joint_states',
            self.listener_callback,
            10
        )

        self.timer = self.create_timer(1.0, self.timer_callback)

    def listener_callback(self, msg):
        self.count += 1

    def timer_callback(self):
        self.get_logger().info(f'관절데이터 수신횟수 {self.count}회')

def main(args=None):
    rclpy.init(args=args)
    node = HelloNode()
    rclpy.spin(node) # 프로그램이 안 꺼지고 계속 돌게 만듦
    node.destroy_node()
    rclpy.shutdown()
    
if __name__ == '__main__':
    main()