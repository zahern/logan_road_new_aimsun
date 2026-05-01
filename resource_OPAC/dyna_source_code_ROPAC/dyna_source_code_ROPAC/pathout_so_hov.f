      subroutine pathout_so_hov(i,j,k,mucindex,node_sum,node_number)

      use muc_mod
      integer mucindex
      integer i, j, k, node_sum, node_number
c --
c -- INPUT
c -- None

c -- 
c -- OUTPUT
c -- sopath 
      
	sopath_hov(i,j,mucindex,1) = k
		
c --  add the destination to the nodesum
      sopolicy_hov(i,j,mucindex,1)%nodesum = node_sum
      sopolicy_hov(i,j,mucindex,1)%nodenumber = node_number
      sopolicy_hov(i,j,mucindex,1)%prob = 1.0

      return
      end  


