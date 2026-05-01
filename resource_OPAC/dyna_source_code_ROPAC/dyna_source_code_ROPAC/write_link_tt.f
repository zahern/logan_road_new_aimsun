      subroutine write_link_tt

      use muc_mod
c      use bcdtr_mod
	  
c      print *, 'alex181'
		
      open(file='linkstraveltime.txt',unit=25,status='unknown')
	  
      write(25,*) jj,noofarcs
	  
      do j=1,jj
           write(25,100) (linktraveltime(j,jn),jn=1,noofarcs)
      enddo
		
      close(25)
	  
c      do j=1,noofarcs
c      if(linktraveltime(460,j).gt.0.001) print *, linktraveltime(460,j)
c      enddo
	  
      deallocate(linktraveltime)

100	  format(700f8.3)

c      print *, 'alex182'	 
	  
      return
      end	  
